"""Punto de entrada del agente en Amazon Bedrock AgentCore Runtime.

AgentCore Runtime crea un microVM aislado por sesión (runtimeSessionId) y llama a la función marcada con
@app.entrypoint en cada invocación. La memoria de la conversación vive en AgentCore Memory, así que el
contexto sobrevive aunque el microVM se detenga por inactividad.

El runtime tiene un authorizer JWT de Cognito: solo llegan aquí las peticiones con un access token válido
del user pool del laboratorio. El usuario (dueño del álbum) sale de ese token, no del payload.
"""

import base64
import json
import os
import re
from datetime import date
from pathlib import Path

from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from strands import Agent
from strands.models import BedrockModel

from acciones import ACCIONES
from herramientas import buscar_catalogo, buscar_mundial, herramientas_para

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = os.environ["MODEL_ID"]
MEMORY_ID = os.environ["MEMORY_ID"]
SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

app = BedrockAgentCoreApp()

# Un agente por (sesión, usuario). El microVM es de una sola sesión, así que esto casi siempre tiene un elemento.
_agentes: dict[tuple[str, str], Agent] = {}


def usuario_del_token(context: RequestContext) -> str:
    """Lee el usuario del access token de Cognito (header Authorization, permitido en el runtime).

    No se verifica la firma: AgentCore ya validó el token (firma, emisor, expiración y cliente) antes de
    llamar al agente. Sin token (pruebas locales) el usuario es "estudiante".
    """
    token = (context.request_headers or {}).get("Authorization", "").removeprefix("Bearer ").strip()
    claims = {}
    if token.count(".") == 2:
        carga = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(carga + "=" * (-len(carga) % 4)))
    usuario = claims.get("username") or claims.get("cognito:username") or "estudiante"
    # Solo letras, números, "-" y "_": es la partition key del álbum y el actorId de AgentCore Memory.
    return re.sub(r"[^a-z0-9_-]+", "-", usuario.strip().lower()).strip("-") or "estudiante"


def crear_agente(session_id: str, actor_id: str) -> Agent:
    memoria = AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id),
        region_name=REGION,
    )
    modelo = BedrockModel(
        model_id=MODEL_ID,
        region_name=REGION,
        # Siempre fija max_tokens: sin él Bedrock reserva cuota para el máximo del modelo.
        max_tokens=2048,
        temperature=0.2,
    )
    return Agent(
        model=modelo,
        system_prompt=f"{SYSTEM_PROMPT}\n\nFecha actual: {date.today().isoformat()}.",
        # El álbum que ve el agente es el del usuario de la conversación (owner = actor_id).
        tools=[buscar_mundial, buscar_catalogo, *herramientas_para(actor_id)],
        session_manager=memoria,
        callback_handler=None,
    )


async def conversar(prompt: str, session_id: str, actor_id: str) -> dict:
    """Un turno de conversación: la respuesta completa y las herramientas que usó el agente."""
    clave = (session_id, actor_id)
    if clave not in _agentes:
        _agentes[clave] = crear_agente(session_id, actor_id)
    resultado = await _agentes[clave].invoke_async(prompt)
    return {"respuesta": str(resultado).strip(), "herramientas": list(resultado.metrics.tool_metrics)}


@app.entrypoint
async def invocar(payload: dict, context: RequestContext):
    """Dos tipos de petición:

    - {"prompt": "..."}: un turno de conversación con el agente.
    - {"accion": "album" | "subir_documento" | "sincronizar_kb" | "estado_kb", ...}: botones del frontend,
      sin modelo de por medio.

    Las dos devuelven JSON.
    """
    usuario = usuario_del_token(context)

    accion = payload.get("accion")
    if accion:
        if accion not in ACCIONES:
            return {"error": f"Acción desconocida: {accion}"}
        return ACCIONES[accion](usuario, payload)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return {"error": "Escribe un mensaje."}
    # Fuera de AgentCore (pruebas locales) no hay sessionId: usamos uno fijo.
    session_id = context.session_id or "sesion-local-0000000000000000000000"
    return await conversar(prompt, session_id, usuario)


if __name__ == "__main__":
    app.run()
