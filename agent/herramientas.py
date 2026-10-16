"""Herramientas del agente: búsqueda en la base de conocimiento (RAG) y CRUD del álbum en DynamoDB.

Cada función con @tool se convierte en una herramienta: Strands lee su docstring y sus tipos para
describírsela al modelo, y el modelo decide cuándo llamarla.
"""

import json
import os
import re
import unicodedata
from functools import cache
from decimal import Decimal
from pathlib import PurePosixPath

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError
from strands import tool

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
TABLE_NAME = os.environ["TABLE_NAME"]
CATALOGO_TABLE = os.environ["CATALOGO_TABLE"]

_kb = boto3.client("bedrock-agent-runtime")
_tabla = boto3.resource("dynamodb").Table(TABLE_NAME)
_tabla_catalogo = boto3.resource("dynamodb").Table(CATALOGO_TABLE)


def _json(valor) -> str:
    """DynamoDB devuelve los números como Decimal; los pasamos a int para el modelo."""
    return json.dumps(valor, ensure_ascii=False, default=lambda d: int(d) if isinstance(d, Decimal) else str(d))


def _fuente(location: dict) -> str:
    """Busca la URI del documento dentro de la ubicación que devuelve el conector."""
    for valor in location.values():
        if isinstance(valor, dict):
            uri = valor.get("uri") or valor.get("url")
            if uri:
                return PurePosixPath(uri).name
    return "desconocida"


# --- RAG: base de conocimiento administrada de Bedrock -------------------------------------------


@tool
def buscar_mundial(consulta: str) -> str:
    """Busca en la base de conocimiento del Mundial 2026: partidos, resultados, selecciones,
    planteles, jugadores, estadios y árbitros. Devuelve fragmentos de documentos con su fuente.

    Args:
        consulta: Texto de búsqueda con palabras clave específicas (por ejemplo "final Mundial 2026 resultado").
    """
    respuesta = _kb.retrieve(
        knowledgeBaseId=KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": consulta},
        # Una base administrada usa managedSearchConfiguration (búsqueda híbrida + re-ranking incluidos).
        retrievalConfiguration={"managedSearchConfiguration": {"numberOfResults": 8}},
    )
    fragmentos = [
        {
            "fuente": _fuente(r.get("location", {})),
            "puntaje": round(r.get("score", 0), 3),
            "texto": r.get("content", {}).get("text", "")[:1500],
        }
        for r in respuesta.get("retrievalResults", [])
    ]
    return _json(fragmentos) if fragmentos else "No se encontraron resultados."


# --- CRUD: tracker del álbum en DynamoDB ----------------------------------------------------------

ESTADOS = ("falta", "tengo", "repetida")
_CODIGO = re.compile(r"^([A-Z]{2,3})\s*-?\s*(\d{1,3})$")


def normalizar_codigo(codigo: str) -> str | None:
    """Acepta "mex 15", "MEX15" o "MEX-15" y devuelve "MEX-15". La lámina del logo de Panini es "00"."""
    codigo = codigo.strip().upper()
    if codigo == "00":
        return codigo
    coincidencia = _CODIGO.match(codigo)
    return f"{coincidencia[1]}-{int(coincidencia[2])}" if coincidencia else None


# --- Catálogo: qué jugador es cada lámina (tabla de solo lectura) -------------------------------


@cache
def _catalogo() -> dict[str, dict]:
    """Lee el catálogo completo una vez por microVM (~1.100 ítems): es pequeño y no cambia."""
    items, kwargs = [], {}
    while True:
        pagina = _tabla_catalogo.scan(**kwargs)
        items += pagina.get("Items", [])
        if "LastEvaluatedKey" not in pagina:
            return {i["codigo"]: i for i in items}
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _con_jugador(item: dict) -> dict:
    """Agrega jugador y país del catálogo a un ítem del tracker."""
    info = _catalogo().get(item["codigo"], {})
    return {"jugador": info.get("jugador", "?"), "pais": info.get("pais", "?"), **item}


@tool
def buscar_catalogo(consulta: str) -> str:
    """Busca en el catálogo del álbum Panini 2026 (lista base + Update Set) qué jugador es cada lámina.
    Acepta un código ("ARG-17"), un jugador ("Messi") o un país en inglés ("Colombia", "Spain").

    Args:
        consulta: Código de lámina, nombre (o parte del nombre) del jugador, o país.
    """
    catalogo = _catalogo()
    codigo = normalizar_codigo(consulta)
    if codigo:
        return _json(catalogo[codigo]) if codigo in catalogo else f"{codigo} no está en el catálogo."
    buscado = _sin_tildes(consulta.strip())
    encontrados = sorted(
        (i for i in catalogo.values() if buscado in _sin_tildes(i["jugador"]) or buscado == _sin_tildes(i["pais"])),
        key=lambda i: (i["codigo"].split("-")[0], int(i["codigo"].split("-")[-1])),
    )
    if not encontrados:
        return f"No hay láminas para {consulta!r}. Si es un país, escríbelo en inglés (por ejemplo Spain)."
    return _json(encontrados[:40]) + ("" if len(encontrados) <= 40 else f"\n(y {len(encontrados) - 40} más)")


def _error_codigo(codigo: str) -> str:
    return (f"Código inválido: {codigo!r}. Usa el código de la sección y el número, por ejemplo MEX-15, "
            "FWC-4, CC-7 o UPD-12. Si tienes el nombre del jugador, búscalo con buscar_catalogo.")


def album_de(owner: str) -> list[dict]:
    """Todas las láminas registradas de un usuario. Query por la partition key: solo lee su álbum."""
    items, kwargs = [], {"KeyConditionExpression": Key("owner").eq(owner)}
    while True:
        pagina = _tabla.query(**kwargs)
        items += pagina.get("Items", [])
        if "LastEvaluatedKey" not in pagina:
            return sorted(items, key=lambda i: (i["grupo"], int(i["numero"])))
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]


def herramientas_para(owner: str) -> list:
    """Crea las herramientas del álbum ligadas a un usuario (el `owner` de cada ítem)."""

    @tool
    def resumen_album() -> str:
        """Resume el álbum del usuario: cuántas láminas le faltan, cuántas tiene repetidas y cuántas
        copias puede cambiar, en total y por sección (selección, FWC o CC)."""
        items = album_de(owner)
        por_grupo: dict[str, dict] = {}
        for i in items:
            g = por_grupo.setdefault(i["grupo"], {"faltan": 0, "repetidas": 0})
            if i["estado"] == "falta":
                g["faltan"] += 1
            elif i["estado"] == "repetida":
                g["repetidas"] += int(i["repetidas"])
        return _json({
            "faltan": sum(i["estado"] == "falta" for i in items),
            "laminas_repetidas": sum(i["estado"] == "repetida" for i in items),
            "copias_para_cambiar": sum(int(i["repetidas"]) for i in items),
            "por_seccion": por_grupo,
        })

    @tool
    def listar_laminas(estado: str = "", grupo: str = "") -> str:
        """Lista las láminas registradas del usuario, con filtros opcionales.

        Args:
            estado: "falta", "tengo" o "repetida" (vacío = todas).
            grupo: Código de la sección: código FIFA de la selección (COL, ARG, MEX...), FWC o CC (vacío = todas).
        """
        items = album_de(owner)
        if estado:
            items = [i for i in items if i["estado"] == estado.lower()]
        if grupo:
            items = [i for i in items if i["grupo"] == grupo.upper()]
        if not items:
            return "No hay láminas registradas con ese filtro."
        return _json([_con_jugador({k: i[k] for k in ("codigo", "estado", "repetidas", "notas") if k in i})
                      for i in items])

    @tool
    def consultar_lamina(codigo: str) -> str:
        """Consulta el estado de una lámina del usuario. Si no está registrada, el usuario la tiene sin repetir
        (para los álbumes importados de Figuritas App) o aún no la ha registrado.

        Args:
            codigo: Sección y número, por ejemplo "MEX-15", "FWC-4", "CC-7" o "UPD-12".
        """
        normal = normalizar_codigo(codigo)
        if not normal:
            return _error_codigo(codigo)
        item = _tabla.get_item(Key={"owner": owner, "codigo": normal}).get("Item")
        if item:
            return _json(_con_jugador(item))
        return f"{normal} ({_json(_con_jugador({'codigo': normal}))}) no está registrada en el tracker."

    @tool
    def agregar_lamina(codigo: str, estado: str, repetidas: int = 0, notas: str = "") -> str:
        """Registra una lámina que todavía no está en el tracker. Falla si ya existe.

        Args:
            codigo: Sección y número, por ejemplo "COL-5".
            estado: "falta", "tengo" o "repetida".
            repetidas: Copias de sobra para cambiar (solo si el estado es "repetida", mínimo 1).
            notas: Comentario libre (opcional).
        """
        normal = normalizar_codigo(codigo)
        if not normal:
            return _error_codigo(codigo)
        if normal not in _catalogo():
            return f"{normal} no existe en el catálogo del álbum. Revisa el código con buscar_catalogo."
        error = _validar(estado, repetidas)
        if error:
            return error
        item = {"owner": owner, "codigo": normal, "grupo": normal.split("-")[0], "numero": int(normal.split("-")[1]),
                "estado": estado, "repetidas": repetidas, "notas": notas}
        try:
            _tabla.put_item(Item=item, ConditionExpression="attribute_not_exists(codigo)")
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return f"{normal} ya está registrada. Usa actualizar_lamina."
            raise
        return f"Registrada: {_json(item)}"

    @tool
    def actualizar_lamina(codigo: str, estado: str | None = None, repetidas: int | None = None,
                          notas: str | None = None) -> str:
        """Cambia el estado, las copias repetidas o las notas de una lámina ya registrada.

        Args:
            codigo: Sección y número, por ejemplo "RSA-20".
            estado: Nuevo estado: "falta", "tengo" o "repetida" (opcional).
            repetidas: Nuevo total de copias de sobra (opcional). Con 0 copias el estado debe ser "tengo".
            notas: Nuevas notas (opcional).
        """
        normal = normalizar_codigo(codigo)
        if not normal:
            return _error_codigo(codigo)
        actual = _tabla.get_item(Key={"owner": owner, "codigo": normal}).get("Item")
        if not actual:
            return f"{normal} no está registrada. Usa agregar_lamina."
        cambios = {k: v for k, v in {"estado": estado, "repetidas": repetidas, "notas": notas}.items() if v is not None}
        if not cambios:
            return "No hay cambios para aplicar."
        nuevo_estado = cambios.get("estado", actual["estado"])
        if estado is None and repetidas is not None:
            # Cambiar solo las copias define el estado: 0 copias = "tengo", 1 o más = "repetida".
            nuevo_estado = "repetida" if repetidas > 0 else ("tengo" if actual["estado"] == "repetida" else actual["estado"])
            cambios["estado"] = nuevo_estado
        nuevas = cambios.get("repetidas", 0 if nuevo_estado != "repetida" else int(actual["repetidas"]))
        error = _validar(nuevo_estado, nuevas)
        if error:
            return error
        cambios["repetidas"] = nuevas
        respuesta = _tabla.update_item(
            Key={"owner": owner, "codigo": normal},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in cambios),
            ExpressionAttributeNames={f"#{k}": k for k in cambios},
            ExpressionAttributeValues={f":{k}": v for k, v in cambios.items()},
            ReturnValues="ALL_NEW",
        )
        return f"Actualizada: {_json(respuesta['Attributes'])}"

    @tool
    def eliminar_lamina(codigo: str) -> str:
        """Borra una lámina del tracker (por ejemplo, si se registró por error). Confirma con el usuario antes.

        Args:
            codigo: Sección y número de la lámina a borrar.
        """
        normal = normalizar_codigo(codigo)
        if not normal:
            return _error_codigo(codigo)
        respuesta = _tabla.delete_item(Key={"owner": owner, "codigo": normal}, ReturnValues="ALL_OLD")
        return f"Borrada del tracker: {normal}." if "Attributes" in respuesta else f"{normal} no estaba registrada."

    return [resumen_album, listar_laminas, consultar_lamina, agregar_lamina, actualizar_lamina, eliminar_lamina]


def _validar(estado: str, repetidas: int) -> str | None:
    if estado not in ESTADOS:
        return f"Estado inválido: {estado!r}. Usa falta, tengo o repetida."
    if estado == "repetida" and repetidas < 1:
        return "Una lámina repetida necesita al menos 1 copia de sobra; si ya no tiene copias, su estado es 'tengo'."
    if estado != "repetida" and repetidas:
        return "Solo las láminas en estado 'repetida' tienen copias de sobra."
    return None
