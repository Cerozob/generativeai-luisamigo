"""Stack del laboratorio: Parcero, un agente de Strands en AgentCore Runtime con RAG, DynamoDB y frontend web.

Recursos:
  1. Base de conocimiento ADMINISTRADA de Bedrock sobre un bucket con los documentos del Mundial 2026.
  2. Tablas DynamoDB: el tracker del álbum de cada usuario y el catálogo de láminas.
  3. AgentCore Memory (memoria de corto plazo de cada conversación).
  4. Cognito: user pool con managed login y el usuario del estudiante.
  5. AgentCore Runtime (despliegue directo de código desde S3) con un authorizer JWT de Cognito.
  6. Frontend React en S3 + CloudFront. CloudFront también reenvía /runtimes/* a AgentCore (mismo origen).
  7. CodeBuild: empaqueta el agente y publica el frontend y los datos durante el despliegue.

Lo que cambia por estudiante son parámetros de CloudFormation (CfnParameter): la plantilla sintetizada
(`cdk synth`) se despliega desde la consola sin instalar nada.
"""

from pathlib import Path

from aws_cdk import Aws, CfnOutput, CfnParameter, Duration, Fn, RemovalPolicy, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from constructs import Construct

from mundial_agente.construccion import Construccion

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DEV_URL = "http://localhost:5173"

# CloudFront Function: las rutas del frontend (/chat, /album...) se sirven con index.html.
_SPA = """function handler(event) {
  var request = event.request;
  if (request.uri.indexOf('.') === -1) { request.uri = '/index.html'; }
  return request;
}"""


class AgenteMundialStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, codigo_fuente_por_defecto: str = "", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Parámetros (lo que llena cada estudiante en la consola) ----------------------------------
        correo = CfnParameter(
            self, "CorreoUsuario", type="String",
            description="Tu correo. Cognito te envía ahí la contraseña temporal y el enlace de la aplicación.",
            allowed_pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
            constraint_description="Debe ser un correo válido.",
        )
        usuario = CfnParameter(
            self, "UsuarioDemo", type="String", default="camilo",
            description="Usuario para iniciar sesión. El álbum de ejemplo se carga a su nombre.",
            allowed_pattern=r"^[a-z0-9_-]{3,30}$",
            constraint_description="Entre 3 y 30 caracteres: minúsculas, números, - o _.",
        )
        modelo = CfnParameter(
            self, "ModeloId", type="String", default="global.amazon.nova-2-lite-v1:0",
            description="Modelo o perfil de inferencia de Bedrock para el agente (debe tener acceso habilitado).",
        )
        prefijo = CfnParameter(
            self, "PrefijoDominio", type="String", default="mundial",
            description="Prefijo del dominio de inicio de sesión de Cognito (se le agrega el ID de la cuenta).",
            allowed_pattern=r"^[a-z0-9-]{3,30}$",
            constraint_description="Entre 3 y 30 caracteres: minúsculas, números o -.",
        )
        version = CfnParameter(
            self, "Version", type="String", default="1",
            description="Cámbialo (2, 3...) para volver a construir el agente y el frontend con el código actual.",
        )
        # cdk deploy -c fuente=local sube esta carpeta como asset; la plantilla usa una URL https.
        if self.node.try_get_context("fuente") == "local":
            paquete = s3_assets.Asset(
                self, "CodigoLaboratorio", path=str(ROOT),
                exclude=["cdk.out", ".venv", "**/node_modules", "frontend/dist", "build", "**/__pycache__", "*.zip"],
            )
            codigo_fuente = paquete.s3_object_url
        else:
            paquete = None
            codigo_fuente = CfnParameter(
                self, "CodigoFuente", type="String", default=codigo_fuente_por_defecto,
                description="URL https del zip del laboratorio (por ejemplo, el zip de GitHub).",
                allowed_pattern=r"^https://.+",
                constraint_description="Debe ser una URL https.",
            ).value_as_string
        self.template_options.metadata = {
            "AWS::CloudFormation::Interface": {
                "ParameterGroups": [
                    {"Label": {"default": "Tu usuario"}, "Parameters": ["CorreoUsuario", "UsuarioDemo"]},
                    {"Label": {"default": "Opciones"},
                     "Parameters": ["ModeloId", "PrefijoDominio", "Version"] + ([] if paquete else ["CodigoFuente"])},
                ]
            }
        }

        # --- Buckets -----------------------------------------------------------------------------
        def bucket(bucket_id: str, **props) -> s3.Bucket:
            return s3.Bucket(
                self, bucket_id,
                encryption=s3.BucketEncryption.S3_MANAGED,
                block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
                enforce_ssl=True,
                removal_policy=RemovalPolicy.DESTROY,  # la construcción los vacía al borrar el stack
                **props,
            )

        artefactos = bucket("ArtefactosBucket")  # el zip del agente
        web = bucket("WebBucket")  # el frontend compilado

        # --- Frontend: CloudFront con dos orígenes ----------------------------------------------------
        distribucion = cloudfront.Distribution(
            self, "Distribucion",
            comment="Parcero: frontend del laboratorio y proxy al agente",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(web),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[cloudfront.FunctionAssociation(
                    event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    function=cloudfront.Function(self, "RutasSpa", code=cloudfront.FunctionCode.from_inline(_SPA)),
                )],
            ),
            additional_behaviors={
                # El navegador llama al agente en el mismo dominio y CloudFront lo reenvía a AgentCore Runtime:
                # no hace falta CORS ni una API intermedia. El token de Cognito viaja en Authorization.
                "/runtimes/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        f"bedrock-agentcore.{Aws.REGION}.amazonaws.com",
                        read_timeout=Duration.seconds(60),  # un turno con varias herramientas puede tardar
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
        )
        url_app = f"https://{distribucion.distribution_domain_name}"

        # --- 1. Documentos y base de conocimiento administrada ------------------------------------------
        docs = bucket(
            "DocumentosBucket",
            # El navegador sube documentos directo a S3 con una URL prefirmada.
            cors=[s3.CorsRule(allowed_methods=[s3.HttpMethods.PUT], allowed_origins=[url_app, LOCAL_DEV_URL],
                              allowed_headers=["*"])],
        )
        kb_role = iam.Role(
            self, "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": Aws.ACCOUNT_ID},
                    "ArnLike": {"aws:SourceArn": f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:knowledge-base/*"},
                },
            ),
        )
        docs.grant_read(kb_role)

        knowledge_base = bedrock.CfnKnowledgeBase(
            self, "KnowledgeBase",
            name=f"{Aws.STACK_NAME}-mundial",
            description="Documentos del Mundial 2026 para el agente de la clase",
            role_arn=kb_role.role_arn,
            # MANAGED: Bedrock administra el almacenamiento, los embeddings, el chunking y el re-ranking.
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="MANAGED",
                managed_knowledge_base_configuration=bedrock.CfnKnowledgeBase.ManagedKnowledgeBaseConfigurationProperty(
                    embedding_model_type="MANAGED",
                ),
            ),
        )

        # Incluye la política del rol (lectura del bucket), no solo el rol.
        knowledge_base.node.add_dependency(kb_role)

        data_source = bedrock.CfnDataSource(
            self, "DocumentosDataSource",
            name="documentos-mundial",
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            # Una base MANAGED usa el conector administrado (no el tipo "S3" de las bases clásicas).
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="MANAGED_KNOWLEDGE_BASE_CONNECTOR",
                managed_knowledge_base_connector_configuration=bedrock.CfnDataSource.ManagedKnowledgeBaseConnectorConfigurationProperty(
                    connector_parameters={
                        "type": "S3",
                        "version": "1",
                        # La API pide bucketOwnerAccountId aunque el bucket sea de la misma cuenta.
                        "connectionConfiguration": {"bucketName": docs.bucket_name, "bucketOwnerAccountId": Aws.ACCOUNT_ID},
                        "filterConfiguration": {"inclusionPrefixes": ["mundial/"]},
                    },
                ),
            ),
        )

        # --- 2. Tracker del álbum y catálogo (DynamoDB) ----------------------------------------------
        # Una partición por usuario (owner) y un ítem por lámina (codigo, por ejemplo "MEX-15").
        album = dynamodb.TableV2(
            self, "AlbumTable",
            partition_key=dynamodb.Attribute(name="owner", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="codigo", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Qué jugador es cada lámina (1.114 filas de assets/catalogo/catalogo.csv).
        catalogo = dynamodb.TableV2(
            self, "CatalogoTable",
            partition_key=dynamodb.Attribute(name="codigo", type=dynamodb.AttributeType.STRING),
            billing=dynamodb.Billing.on_demand(),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- 3. Memoria de las conversaciones ----------------------------------------------------------
        memoria = agentcore.Memory(
            self, "Memoria",
            memory_name=f"{construct_id}_memoria",
            description="Memoria de corto plazo de cada conversacion",
            expiration_duration=Duration.days(7),  # el mínimo que admite el servicio
        )

        # --- 4. Cognito ---------------------------------------------------------------------------
        user_pool = cognito.UserPool(
            self, "UserPool",
            feature_plan=cognito.FeaturePlan.ESSENTIALS,  # incluye el managed login
            self_sign_up_enabled=False,  # los usuarios los crea el administrador (la plantilla crea el tuyo)
            sign_in_aliases=cognito.SignInAliases(username=True, email=True),
            sign_in_case_sensitive=False,
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            password_policy=cognito.PasswordPolicy(min_length=8, require_symbols=False),
            user_invitation=cognito.UserInvitationConfig(
                email_subject="Tu acceso a Parcero, el agente del Mundial 2026",
                email_body=(
                    f"Hola. Entra a {url_app} con el usuario {{username}} y la contraseña temporal {{####}}. "
                    "Te pedirá una contraseña nueva."
                ),
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )
        dominio = user_pool.add_domain(
            "Dominio",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=Fn.join("-", [prefijo.value_as_string, Aws.ACCOUNT_ID])
            ),
            managed_login_version=cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
        )
        callbacks = [f"{url_app}/", f"{LOCAL_DEV_URL}/"]
        cliente = user_pool.add_client(
            "WebClient",
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),  # con PKCE desde el navegador
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
                callback_urls=callbacks,
                logout_urls=callbacks,
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
        )
        cognito.CfnManagedLoginBranding(
            self, "EstiloLogin",
            user_pool_id=user_pool.user_pool_id,
            client_id=cliente.user_pool_client_id,
            use_cognito_provided_values=True,
        ).node.add_dependency(dominio)
        cognito.CfnUserPoolUser(
            self, "UsuarioEstudiante",
            user_pool_id=user_pool.user_pool_id,
            username=usuario.value_as_string,
            desired_delivery_mediums=["EMAIL"],
            user_attributes=[
                cognito.CfnUserPoolUser.AttributeTypeProperty(name="email", value=correo.value_as_string),
                cognito.CfnUserPoolUser.AttributeTypeProperty(name="email_verified", value="true"),
            ],
        )

        # --- 5. Runtime del agente (código desde S3) --------------------------------------------------
        construccion = Construccion(self, "Construccion", codigo_fuente=codigo_fuente)
        if paquete:
            paquete.grant_read(construccion.proyecto)
        clave_agente = f"agente/v{version.value_as_string}/agente.zip"
        paquete_agente = construccion.etapa(
            "PaqueteAgente", "agente",
            {"BUCKET_ARTEFACTOS": artefactos.bucket_name, "CLAVE_AGENTE": clave_agente},
            version=version.value_as_string,
            vaciar_buckets=[artefactos.bucket_name],
        )
        artefactos.grant_put(construccion.proyecto)

        runtime = agentcore.Runtime(
            self, "AgenteRuntime",
            runtime_name=f"{construct_id}_agente",
            description="Parcero: agente Strands del Mundial 2026 con RAG y album en DynamoDB",
            # Despliegue directo de código: un zip con el código y sus dependencias Linux ARM64.
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_s3(
                s3.Location(bucket_name=artefactos.bucket_name, object_key=clave_agente),
                agentcore.AgentCoreRuntime.PYTHON_3_13,
                # opentelemetry-instrument envía trazas y métricas a CloudWatch (AgentCore Observability).
                ["opentelemetry-instrument", "main.py"],
            ),
            # Solo entran peticiones con un access token válido de este user pool y de este cliente.
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_cognito(user_pool, [cliente]),
            # El agente recibe el header Authorization para saber quién es el usuario (dueño del álbum).
            request_header_configuration=agentcore.RequestHeaderConfiguration(allowlisted_headers=["Authorization"]),
            environment_variables={
                "MODEL_ID": modelo.value_as_string,
                "KNOWLEDGE_BASE_ID": knowledge_base.attr_knowledge_base_id,
                "DATA_SOURCE_ID": data_source.attr_data_source_id,
                "DOCS_BUCKET": docs.bucket_name,
                "TABLE_NAME": album.table_name,
                "CATALOGO_TABLE": catalogo.table_name,
                "MEMORY_ID": memoria.memory_id,
                "AGENT_OBSERVABILITY_ENABLED": "true",
                "OTEL_PYTHON_DISTRO": "aws_distro",
                "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
            },
        )
        runtime.node.add_dependency(paquete_agente)  # el zip debe existir antes de crear el runtime
        artefactos.grant_read(runtime)

        # Permisos del agente. El modelo es un parámetro, así que se permite invocar modelos y perfiles de
        # inferencia de Bedrock en general; en producción se limita al ARN del modelo elegido.
        runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:{Aws.PARTITION}:bedrock:*::foundation-model/*",
                f"arn:{Aws.PARTITION}:bedrock:::foundation-model/*",  # destino de un perfil global.
                f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:inference-profile/*",
            ],
        ))
        runtime.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:Retrieve", "bedrock:GetDataSource", "bedrock:StartIngestionJob",
                     "bedrock:GetIngestionJob", "bedrock:ListIngestionJobs"],
            resources=[knowledge_base.attr_knowledge_base_arn],
        ))
        album.grant_read_write_data(runtime)
        catalogo.grant_read_data(runtime)
        memoria.grant_read_short_term_memory(runtime)
        memoria.grant_write(runtime)
        docs.grant_put(runtime, "mundial/subidos/*")  # para firmar las URLs de subida

        # --- 6. Publicación del frontend y de los datos ---------------------------------------------
        config_frontend = self.to_json_string({
            "region": Aws.REGION,
            "userPoolId": user_pool.user_pool_id,
            "userPoolClientId": cliente.user_pool_client_id,
            "cognitoDomain": f"{dominio.domain_name}.auth.{Aws.REGION}.amazoncognito.com",
            # Con el ID del runtime (en vez del ARN) no hay que codificar la ruta.
            "agentUrl": f"/runtimes/{runtime.agent_runtime_id}/invocations?qualifier=DEFAULT&accountId={Aws.ACCOUNT_ID}",
        })
        construccion.etapa(
            "PublicarWeb", "web",
            {
                "CONFIG_FRONTEND": config_frontend,
                "BUCKET_WEB": web.bucket_name,
                "BUCKET_DOCS": docs.bucket_name,
                "DISTRIBUCION": distribucion.distribution_id,
                "TABLA_ALBUM": album.table_name,
                "TABLA_CATALOGO": catalogo.table_name,
                "USUARIO_DEMO": usuario.value_as_string,
                "KB_ID": knowledge_base.attr_knowledge_base_id,
                "DS_ID": data_source.attr_data_source_id,
            },
            version=version.value_as_string,
            vaciar_buckets=[web.bucket_name, docs.bucket_name],
        )
        web.grant_read_write(construccion.proyecto)
        web.grant_delete(construccion.proyecto)
        docs.grant_read_write(construccion.proyecto)
        album.grant_write_data(construccion.proyecto)
        catalogo.grant_write_data(construccion.proyecto)
        distribucion.grant_create_invalidation(construccion.proyecto)
        construccion.proyecto.add_to_role_policy(iam.PolicyStatement(
            actions=["bedrock:GetDataSource", "bedrock:StartIngestionJob"],
            resources=[knowledge_base.attr_knowledge_base_arn],
        ))
        # La función de la construcción vacía los buckets al borrar el stack.
        buckets = (artefactos, web, docs)
        construccion.funcion.add_to_role_policy(iam.PolicyStatement(
            actions=["s3:ListBucket", "s3:ListBucketVersions", "s3:DeleteObject", "s3:DeleteObjectVersion"],
            resources=[b.bucket_arn for b in buckets] + [b.arn_for_objects("*") for b in buckets],
        ))

        CfnOutput(self, "UrlAplicacion", value=url_app, description="Abre esta URL e inicia sesión")
        CfnOutput(self, "Usuario", value=usuario.value_as_string)
        CfnOutput(self, "AgentRuntimeArn", value=runtime.agent_runtime_arn)
        CfnOutput(self, "KnowledgeBaseId", value=knowledge_base.attr_knowledge_base_id)
        CfnOutput(self, "DataSourceId", value=data_source.attr_data_source_id)
        CfnOutput(self, "TablaAlbum", value=album.table_name)
        CfnOutput(self, "TablaCatalogo", value=catalogo.table_name)
        CfnOutput(self, "BucketDocumentos", value=docs.bucket_name)
        CfnOutput(self, "UserPoolId", value=user_pool.user_pool_id)
