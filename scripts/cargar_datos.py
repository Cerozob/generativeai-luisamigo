"""Carga los datos de ejemplo del laboratorio. Lo ejecuta CodeBuild durante el despliegue.

  1. Álbum de ejemplo: assets/album/*.txt (exportación de Figuritas App) a nombre del usuario demo.
  2. Catálogo del álbum: assets/catalogo/catalogo.csv (código, jugador, país).
  3. Primera ingesta de la base de conocimiento, si se pasan --kb y --ds.

Ejecutar a mano (desde la raíz del laboratorio):
  python scripts/cargar_datos.py --tabla-album <tabla> --tabla-catalogo <tabla> --usuario camilo
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import boto3

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from mundial_agente.figuritas import leer_exportacion  # noqa: E402


def cargar_album(tabla: str, usuario: str) -> int:
    items = [
        item
        for archivo in sorted((RAIZ / "assets" / "album").glob("*.txt"))
        for item in leer_exportacion(archivo.read_text(encoding="utf-8"), usuario)
    ]
    with boto3.resource("dynamodb").Table(tabla).batch_writer(overwrite_by_pkeys=["owner", "codigo"]) as lote:
        for item in items:
            lote.put_item(Item=item)
    return len(items)


def cargar_catalogo(tabla: str) -> int:
    with open(RAIZ / "assets" / "catalogo" / "catalogo.csv", encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    with boto3.resource("dynamodb").Table(tabla).batch_writer(overwrite_by_pkeys=["codigo"]) as lote:
        for fila in filas:
            lote.put_item(Item=fila)
    return len(filas)


def primera_ingesta(kb_id: str, ds_id: str) -> None:
    bedrock = boto3.client("bedrock-agent")
    # En una base administrada, la fuente de datos se crea de forma asíncrona (CREATING -> AVAILABLE).
    for _ in range(60):
        estado = bedrock.get_data_source(knowledgeBaseId=kb_id, dataSourceId=ds_id)["dataSource"]["status"]
        if estado == "AVAILABLE":
            break
        print(f"Fuente de datos: {estado}. Esperando...")
        time.sleep(10)
    job = bedrock.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)["ingestionJob"]
    # No esperamos a que termine: el frontend muestra el estado en la página Documentos.
    print(f"Ingesta iniciada: {job['ingestionJobId']} ({job['status']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tabla-album", required=True)
    parser.add_argument("--tabla-catalogo", required=True)
    parser.add_argument("--usuario", required=True, help="Dueño del álbum de ejemplo (usuario de Cognito)")
    parser.add_argument("--kb")
    parser.add_argument("--ds")
    args = parser.parse_args()

    usuario = args.usuario.strip().lower()
    print(f"Álbum de {usuario}: {cargar_album(args.tabla_album, usuario)} láminas")
    print(f"Catálogo: {cargar_catalogo(args.tabla_catalogo)} láminas")
    if args.kb and args.ds:
        primera_ingesta(args.kb, args.ds)
