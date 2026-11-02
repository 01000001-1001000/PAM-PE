"""Lectura y validación de acciones.json.

Principio: el fichero lo escribe una persona, así que DESCONFIAMOS de él. Se
comprueba todo y se reportan TODOS los problemas de una vez, cada uno con la
ruta exacta del campo que falla. Todo error aquí es un ``ConfigError``
(código de salida 3), nunca un traceback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .acciones import Accion, Cadena
from .errores import AccionNoValida, ConfigError

VERSION_ESQUEMA = 1  # versión del formato de acciones.json que sabemos leer


@dataclass(frozen=True)
class Configuracion:
    """Resultado de cargar acciones.json: las acciones ya validadas y listas."""

    ruta: Path
    acciones: dict[str, Accion]

    def obtener(self, nombre: str) -> Accion:
        """Busca una acción por nombre. Error de USO (código 2) si no existe."""
        accion = self.acciones.get(nombre)
        if accion is None:
            disponibles = ", ".join(sorted(self.acciones))
            raise AccionNoValida(
                f"No existe la acción '{nombre}'.",
                pista=f"Acciones disponibles: {disponibles}. Mira `tareas acciones`.",
            )
        return accion


def cargar(ruta: Path) -> Configuracion:
    """Lee, valida y construye las acciones de ``ruta``.

    Raises:
        ConfigError: el fichero no existe, no es JSON o tiene campos inválidos.
    """
    ruta = ruta.expanduser()
    if not ruta.is_file():
        raise ConfigError(
            f"No encuentro el fichero de acciones: {ruta}",
            pista="Crea un acciones.json en esta carpeta o indica otro con --config RUTA.",
        )

    # utf-8-sig: lee UTF-8 y descarta el BOM que añade el Bloc de notas de
    # Windows. Sin esto, json.loads fallaría con «Unexpected UTF-8 BOM».
    try:
        texto = ruta.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise ConfigError(f"{ruta.name} no está guardado en UTF-8 (guárdalo como UTF-8).") from None
    except OSError as error:
        raise ConfigError(f"No puedo leer {ruta}: {error.strerror or error}") from None

    try:
        crudo = json.loads(texto)
    except json.JSONDecodeError as error:
        # lineno/colno dicen DÓNDE está el fallo (una coma de más, una comilla...).
        raise ConfigError(
            f"{ruta.name} no es JSON válido: {error.msg} (línea {error.lineno}, columna {error.colno})"
        ) from None

    problemas: list[str] = []
    if not isinstance(crudo, dict):
        raise ConfigError(f"{ruta.name}: el fichero debe contener un objeto JSON {{...}} en la raíz")

    # Claves de primer nivel y versión del esquema.
    for clave in crudo:
        if clave not in ("version", "acciones"):
            problemas.append(f"clave desconocida en la raíz: '{clave}' (solo 'version' y 'acciones')")
    if crudo.get("version") != VERSION_ESQUEMA:
        problemas.append(
            f"version: debe ser {VERSION_ESQUEMA} (encontrado: {crudo.get('version', 'nada')!r})"
        )
    lista = crudo.get("acciones")
    if not isinstance(lista, list) or not lista:
        problemas.append("acciones: debe ser una lista con al menos una acción")
        lista = []

    # Primera pasada: construir cada acción, acumulando los problemas.
    acciones: dict[str, Accion] = {}
    for indice, datos in enumerate(lista):
        try:
            accion = Accion.desde_dict(datos, indice)
        except ConfigError as error:
            problemas.append(error.mensaje)
            continue  # seguimos para reportar también los fallos de las demás
        if accion.nombre in acciones:
            problemas.append(f"acciones[{indice}]: el nombre '{accion.nombre}' está repetido")
            continue
        acciones[accion.nombre] = accion

    # Segunda pasada: enlazar las cadenas con las acciones que citan.
    for nombre, accion in list(acciones.items()):
        if isinstance(accion, Cadena):
            try:
                acciones[nombre] = accion.enlazar(acciones)
            except ConfigError as error:
                problemas.append(error.mensaje)

    if problemas:
        raise ConfigError(
            f"{ruta.name} no es válido ({len(problemas)} problema{'s' if len(problemas) != 1 else ''}):",
            problemas=problemas,
            pista="Corrige los campos indicados y vuelve a ejecutar `tareas validar`.",
        )
    return Configuracion(ruta=ruta, acciones=acciones)
