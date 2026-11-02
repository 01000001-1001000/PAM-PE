"""Funciones pequeñas y reutilizables que no pertenecen a ningún otro módulo.

Son funciones PURAS (mismo argumento → mismo resultado, sin efectos
secundarios, salvo ``hash_fichero`` que lee del disco), por eso son fáciles de
probar.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path


def tamano_humano(numero_bytes: int) -> str:
    """Convierte bytes en un texto legible: 1536 -> '1.5 KB'."""
    tamano = float(numero_bytes)
    for unidad in ("B", "KB", "MB", "GB"):
        # Mientras quepa en la unidad actual (o sea la última), se muestra.
        if tamano < 1024 or unidad == "GB":
            # Los bytes se muestran sin decimales; el resto, con uno.
            return f"{tamano:.0f} {unidad}" if unidad == "B" else f"{tamano:.1f} {unidad}"
        tamano /= 1024
    raise AssertionError("inalcanzable: el bucle siempre retorna en 'GB'")


def hash_fichero(ruta: Path, bloque: int = 1024 * 1024) -> str:
    """Devuelve el SHA-256 del CONTENIDO de un fichero.

    Se lee por bloques de 1 MB para no cargar un fichero de varios GB entero
    en memoria. Dos ficheros con el mismo hash tienen (a efectos prácticos)
    el mismo contenido aunque se llamen distinto: así se detectan duplicados.
    """
    resumen = hashlib.sha256()
    with ruta.open("rb") as fichero:
        # iter(callable, centinela): llama a read() hasta que devuelva b"" (fin).
        for trozo in iter(lambda: fichero.read(bloque), b""):
            resumen.update(trozo)
    return resumen.hexdigest()


# Nombres que Windows prohíbe como nombre de fichero (con cualquier extensión).
_RESERVADOS_WINDOWS = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {
    f"lpt{i}" for i in range(1, 10)
}


def sanear_nombre(texto: str, max_largo: int = 60) -> str:
    """Convierte un texto cualquiera en un nombre de fichero seguro.

    - Quita tildes y diacríticos ('Física' -> 'fisica').
    - Pasa a minúsculas y cambia todo lo que no sea letra/número por '-'.
    - Limita la longitud y evita los nombres reservados de Windows.

    Se usa con lo que devuelve la IA: nunca hay que fiarse de un nombre que
    viene de fuera (podría traer '/', '..' o caracteres prohibidos).
    """
    # NFKD separa la letra de su tilde ('é' -> 'e' + acento); encode ascii
    # con "ignore" descarta el acento y cualquier carácter no ASCII.
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    # Cualquier racha de caracteres no alfanuméricos pasa a ser un solo guion.
    limpio = re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")
    limpio = limpio[:max_largo].strip("-")
    if limpio in _RESERVADOS_WINDOWS:
        limpio += "-doc"
    return limpio


def nombre_libre(destino: Path, reservados: set[str]) -> Path:
    """Devuelve una ruta que NO existe todavía, para no sobrescribir nunca.

    Si ``destino`` ya existe (o ya lo hemos reservado en este mismo plan) se
    prueba con ``nombre_1.ext``, ``nombre_2.ext``... ``reservados`` es el
    conjunto de rutas (en minúsculas) ya prometidas a otras operaciones del
    plan: durante una simulación nada se escribe en disco, así que sin él dos
    ficheros podrían acabar con el mismo destino.
    """
    candidato = destino
    contador = 1
    # casefold(): comparación sin distinguir mayúsculas (Windows y macOS no distinguen).
    while candidato.exists() or str(candidato).casefold() in reservados:
        candidato = destino.with_name(f"{destino.stem}_{contador}{destino.suffix}")
        contador += 1
    reservados.add(str(candidato).casefold())
    return candidato
