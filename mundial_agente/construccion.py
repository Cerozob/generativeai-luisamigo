"""Construcción dentro de la cuenta: un proyecto de CodeBuild y un custom resource que lo ejecuta.

Así la plantilla no depende de nada instalado en el computador de quien despliega (ni Python, ni Node, ni
Docker): CodeBuild descarga el código del laboratorio y corre scripts/construir.sh durante el despliegue.
"""

from aws_cdk import CustomResource, Duration
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

# Código del custom resource: arranca el build, espera a que termine y responde a CloudFormation.
# Va en línea (sin assets) para que la plantilla sintetizada se pueda desplegar sola desde la consola.
_CODIGO_CUSTOM_RESOURCE = """
import time
import boto3
import cfnresponse

codebuild = boto3.client("codebuild")
s3 = boto3.resource("s3")


def handler(event, context):
    props = event["ResourceProperties"]
    fisico = props["Etapa"]  # fijo por etapa: un cambio de id haría que CloudFormation borre el anterior
    try:
        if event["RequestType"] == "Delete":
            # Los buckets deben quedar vacíos para que CloudFormation pueda borrarlos.
            for bucket in props.get("VaciarBuckets", []):
                try:
                    s3.Bucket(bucket).object_versions.delete()
                except Exception as error:
                    print(f"No se pudo vaciar {bucket}: {error}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, fisico)
            return
        variables = [{"name": k, "value": v, "type": "PLAINTEXT"} for k, v in props["Variables"].items()]
        build = codebuild.start_build(projectName=props["Proyecto"], environmentVariablesOverride=variables)["build"]
        print(f"Build {build['id']} iniciado")
        while build["buildStatus"] == "IN_PROGRESS":
            if context.get_remaining_time_in_millis() < 30000:
                raise RuntimeError(f"El build {build['id']} no terminó a tiempo")
            time.sleep(15)
            build = codebuild.batch_get_builds(ids=[build["id"]])["builds"][0]
        if build["buildStatus"] != "SUCCEEDED":
            raise RuntimeError(f"CodeBuild terminó en {build['buildStatus']}: revisa los logs del build {build['id']}")
        cfnresponse.send(event, context, cfnresponse.SUCCESS, {}, fisico)
    except Exception as error:
        print(error)
        cfnresponse.send(event, context, cfnresponse.FAILED, {}, fisico, reason=str(error)[:500])
"""

_BUILDSPEC = {
    "version": "0.2",
    "phases": {
        "install": {"runtime-versions": {"nodejs": "22", "python": "3.13"}},
        "build": {
            "commands": [
                "mkdir -p /tmp/lab && cd /tmp/lab",
                # El código del laboratorio: un zip en S3 (cdk deploy) o en una URL https (plantilla).
                'case "$CODIGO_FUENTE" in s3://*) aws s3 cp "$CODIGO_FUENTE" codigo.zip ;;'
                ' *) curl -fsSL "$CODIGO_FUENTE" -o codigo.zip ;; esac',
                "unzip -q codigo.zip -d codigo",
                # El zip de GitHub trae una carpeta raíz; el de cdk deploy no. Se busca la raíz del laboratorio.
                'cd "$(dirname "$(find codigo -maxdepth 5 -name construir.sh -path "*/scripts/*" | head -1)")/.."',
                'bash scripts/construir.sh "$ETAPA"',
            ]
        },
    },
}


class Construccion(Construct):
    """Proyecto de CodeBuild compartido por las etapas y la función que las ejecuta."""

    def __init__(self, scope: Construct, construct_id: str, *, codigo_fuente: str) -> None:
        super().__init__(scope, construct_id)
        self._codigo_fuente = codigo_fuente

        self.proyecto = codebuild.Project(
            self,
            "Proyecto",
            description="Empaqueta el agente y publica el frontend y los datos del laboratorio",
            build_spec=codebuild.BuildSpec.from_object(_BUILDSPEC),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2023_5,
                compute_type=codebuild.ComputeType.SMALL,
            ),
            timeout=Duration.minutes(20),
        )

        self.funcion = lambda_.Function(
            self,
            "Ejecutor",
            description="Custom resource: ejecuta una etapa de CodeBuild y espera el resultado",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="index.handler",
            code=lambda_.Code.from_inline(_CODIGO_CUSTOM_RESOURCE),
            timeout=Duration.minutes(15),
        )
        self.funcion.add_to_role_policy(
            iam.PolicyStatement(
                actions=["codebuild:StartBuild", "codebuild:BatchGetBuilds"], resources=[self.proyecto.project_arn]
            )
        )

    def etapa(self, construct_id: str, etapa: str, variables: dict[str, str], *, version: str,
              vaciar_buckets: list[str]) -> CustomResource:
        """Una ejecución de scripts/construir.sh <etapa>. Se repite cuando cambian sus variables o la versión."""
        return CustomResource(
            self,
            construct_id,
            service_token=self.funcion.function_arn,
            resource_type="Custom::Construccion",
            properties={
                "Proyecto": self.proyecto.project_name,
                "Etapa": etapa,
                "Version": version,
                "Variables": {"ETAPA": etapa, "CODIGO_FUENTE": self._codigo_fuente, **variables},
                "VaciarBuckets": vaciar_buckets,
            },
        )

