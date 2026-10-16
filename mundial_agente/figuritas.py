"""Convierte la lista que exporta Figuritas App ("I need" / "Swaps") en ítems del álbum para DynamoDB.

Formato de cada línea de la exportación:  `MEX 🇲🇽: 4 (×2), 5, 8`
  - "I need" = láminas que faltan.
  - "Swaps"  = láminas repetidas; "(×2)" indica cuántas copias de sobra hay (sin número = 1).
Las láminas que no aparecen en la lista son las que el dueño ya tiene, sin repetir.

Ejecutar solo para ver el resultado:  python -m mundial_agente.figuritas assets/album/camilo.txt
"""

import re
import sys
from pathlib import Path

_SECCIONES = {"i need": "falta", "swaps": "repetida"}
_LINEA = re.compile(r"^(?P<seccion>[^:]+):\s*(?P<numeros>\d[\d\s,()×x]*)$")
_NUMERO = re.compile(r"(\d+)(?:\s*\((?:×|x)(\d+)\))?")


def leer_exportacion(texto: str, owner: str) -> list[dict]:
    items: dict[str, dict] = {}
    estado = None
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.lower() in _SECCIONES:
            estado = _SECCIONES[linea.lower()]
            continue
        coincidencia = _LINEA.match(linea)
        if not estado or not coincidencia:
            continue
        seccion = coincidencia["seccion"].strip()
        grupo = seccion.split()[0].upper()  # "MEX 🇲🇽" -> MEX, "CC - Coca-Cola 🥤" -> CC
        for numero, copias in _NUMERO.findall(coincidencia["numeros"]):
            codigo = f"{grupo}-{int(numero)}"
            if codigo in items:
                raise ValueError(f"{codigo} aparece dos veces en la exportación")
            items[codigo] = {
                "owner": owner,
                "codigo": codigo,
                "grupo": grupo,
                "seccion": seccion,
                "numero": int(numero),
                "estado": estado,
                "repetidas": int(copias or 1) if estado == "repetida" else 0,
            }
    return sorted(items.values(), key=lambda i: (i["grupo"], i["numero"]))


def leer_albumes(carpeta: Path) -> list[dict]:
    """Un archivo por usuario: assets/album/<owner>.txt."""
    return [item for archivo in sorted(carpeta.glob("*.txt"))
            for item in leer_exportacion(archivo.read_text(encoding="utf-8"), archivo.stem.lower())]


if __name__ == "__main__":
    for ruta in sys.argv[1:]:
        album = leer_exportacion(Path(ruta).read_text(encoding="utf-8"), Path(ruta).stem.lower())
        faltan = [i for i in album if i["estado"] == "falta"]
        repetidas = [i for i in album if i["estado"] == "repetida"]
        print(f"{ruta}: {len(faltan)} faltan, {len(repetidas)} repetidas "
              f"({sum(i['repetidas'] for i in repetidas)} copias para cambiar)")
