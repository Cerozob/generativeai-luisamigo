"""Acciones de los botones del frontend: se ejecutan en el mismo runtime, pero sin pasar por el modelo.

Así el frontend no necesita otra API (API Gateway + Lambda): todo entra por el endpoint del runtime,
protegido por el mismo authorizer de Cognito.
"""

import json
import os
import re
from decimal import Decimal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from herramientas import _con_jugador, album_de

REGION = os.environ.get("AWS_REGION", "us-east-1")
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
DATA_SOURCE_ID = os.environ["DATA_SOURCE_ID"]
DOCS_BUCKET = os.environ["DOCS_BUCKET"]

# La fuente de datos de la base de conocimiento solo lee el prefijo mundial/.
PREFIJO_SUBIDAS = "mundial/subidos"
EXTENSIONES = {".pdf", ".txt", ".md", ".html", ".htm", ".csv", ".doc", ".docx", ".xls", ".xlsx"}
MAX_BYTES = 50 * 1024 * 1024

_s3 = boto3.client("s3", region_name=REGION, config=Config(signature_version="s3v4"))
_bedrock = boto3.client("bedrock-agent", region_name=REGION)


def _numeros(valor):
    """DynamoDB devuelve Decimal; JSON necesita int."""
    return json.loads(json.dumps(valor, default=lambda d: int(d) if isinstance(d, Decimal) else str(d)))


def album(usuario: str, _payload: dict) -> dict:
    """Las láminas registradas del usuario, con jugador y país del catálogo."""
    laminas = [_con_jugador(i) for i in album_de(usuario)]
    return _numeros({
        "usuario": usuario,
        "faltan": sum(i["estado"] == "falta" for i in laminas),
        "repetidas": sum(i["estado"] == "repetida" for i in laminas),
        "copiasParaCambiar": sum(int(i["repetidas"]) for i in laminas),
        "laminas": laminas,
    })


def subir_documento(usuario: str, payload: dict) -> dict:
    """URL prefirmada para que el navegador suba un documento directo a S3 (sin pasar por el runtime)."""
    nombre = re.sub(r"[^\w.\- ]+", "_", os.path.basename(payload.get("nombre") or "")).strip()
    extension = os.path.splitext(nombre)[1].lower()
    if not nombre or extension not in EXTENSIONES:
        return {"error": f"Formato no admitido. Usa uno de: {', '.join(sorted(EXTENSIONES))}"}
    if int(payload.get("tamano") or 0) > MAX_BYTES:
        return {"error": "El archivo supera 50 MB."}
    tipo = payload.get("tipo") or "application/octet-stream"
    clave = f"{PREFIJO_SUBIDAS}/{usuario}/{nombre}"
    url = _s3.generate_presigned_url(
        "put_object", Params={"Bucket": DOCS_BUCKET, "Key": clave, "ContentType": tipo}, ExpiresIn=300
    )
    return {"url": url, "clave": clave, "tipo": tipo}


def _trabajo(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "id": job["ingestionJobId"],
        "estado": job["status"],
        "inicio": str(job.get("startedAt", "")),
        "fin": str(job.get("updatedAt", "")),
        "estadisticas": job.get("statistics", {}),
        "errores": job.get("failureReasons", []),
    }


def estado_kb(_usuario: str, _payload: dict) -> dict:
    """Estado de la fuente de datos y de la última ingesta."""
    fuente = _bedrock.get_data_source(knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=DATA_SOURCE_ID)["dataSource"]
    trabajos = _bedrock.list_ingestion_jobs(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        dataSourceId=DATA_SOURCE_ID,
        sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
        maxResults=1,
    ).get("ingestionJobSummaries", [])
    return _numeros({"fuente": fuente["status"], "ultimaIngesta": _trabajo(trabajos[0] if trabajos else None)})


def sincronizar_kb(usuario: str, payload: dict) -> dict:
    """Lanza la ingesta (sync): la base vuelve a leer el bucket y procesa lo nuevo o lo que cambió."""
    try:
        job = _bedrock.start_ingestion_job(knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=DATA_SOURCE_ID)
    except ClientError as error:
        # Solo puede haber una ingesta a la vez por fuente de datos.
        if error.response["Error"]["Code"] in ("ConflictException", "ValidationException"):
            return {**estado_kb(usuario, payload), "aviso": error.response["Error"]["Message"]}
        raise
    return _numeros({"fuente": "AVAILABLE", "ultimaIngesta": _trabajo(job["ingestionJob"])})


ACCIONES = {
    "album": album,
    "subir_documento": subir_documento,
    "estado_kb": estado_kb,
    "sincronizar_kb": sincronizar_kb,
}
