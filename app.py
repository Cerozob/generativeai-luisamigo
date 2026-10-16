#!/usr/bin/env python3
"""App de CDK del laboratorio.

- Plantilla para los estudiantes:  cdk synth -c codigo_fuente=https://... > plantilla.yaml
  (no necesita bootstrap ni assets: se despliega desde la consola de CloudFormation).
- Despliegue del instructor con el código local:  cdk deploy -c fuente=local --parameters CorreoUsuario=...
"""

import aws_cdk as cdk

from mundial_agente.agente_stack import AgenteMundialStack

app = cdk.App()
AgenteMundialStack(
    app,
    "AgenteMundial",
    description="Laboratorio IA generativa en AWS: Parcero, agente Strands en AgentCore Runtime con RAG, "
    "DynamoDB y frontend React + Cognito",
    # URL del zip del laboratorio que la plantilla usa por defecto.
    codigo_fuente_por_defecto=app.node.try_get_context("codigo_fuente") or "",
    # Sin regla de versión de bootstrap: la plantilla se despliega en cuentas que nunca usaron CDK.
    synthesizer=cdk.DefaultStackSynthesizer(generate_bootstrap_version_rule=False),
    # Sin región fija: la plantilla sirve en cualquier región con AgentCore y bases administradas.
)
app.synth()
