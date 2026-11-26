"""Funciones para validar el contenido de acciones.json con mensajes claros.

Todas siguen el mismo patrón: reciben el diccionario JSON (``datos``), el
nombre de la clave y la ``ruta`` legible del sitio donde estamos
(p. ej. ``acciones[2] ('renombrar-fotos').filtro``). Si algo está mal lanzan
``ConfigError`` con un mensaje del tipo:

    acciones[2] ('renombrar-fotos').filtro.extensiones: debe ser una lista de textos

Así la persona sabe EXACTAMENTE qué campo arreglar (lo que pide ``tareas validar``).
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable
from typing import Any

from .errores import ConfigError


def _donde(ruta: str, clave: str) -> str:
    """Compone 'ruta.clave' para los mensajes de error."""
    return f"{ruta}.{clave}"


def exigir_texto(datos: dict[str, Any], clave: str, ruta: str) -> str:
    """La clave es OBLIGATORIA y debe ser un texto no vacío."""
    if clave not in datos:
        raise ConfigError(f"{ruta}: falta la clave obligatoria '{clave}'")
    valor = datos[clave]
    if not isinstance(valor, str) or not valor.strip():
        raise ConfigError(f"{_donde(ruta, clave)}: debe ser un texto no vacío")
    return valor.strip()


def texto_opcional(datos: dict[str, Any], clave: str, ruta: str) -> str | None:
    """La clave es opcional; si está, debe ser un texto no vacío."""
    if clave not in datos:
        return None
    return exigir_texto(datos, clave, ruta)


def bool_opcional(datos: dict[str, Any], clave: str, ruta: str, defecto: bool) -> bool:
    """La clave es opcional; si está, debe ser true o false."""
    if clave not in datos:
        return defecto
    valor = datos[clave]
    if not isinstance(valor, bool):
        raise ConfigError(f"{_donde(ruta, clave)}: debe ser true o false (sin comillas)")
    return valor


def numero_opcional(
    datos: dict[str, Any], clave: str, ruta: str, *, entero: bool, minimo: float = 0
) -> float | int | None:
    """La clave es opcional; si está, debe ser un número >= ``minimo``."""
    if clave not in datos:
        return None
    valor = datos[clave]
    # OJO: en Python True es un int (True == 1). Hay que descartarlo a mano.
    tipos = (int,) if entero else (int, float)
    if isinstance(valor, bool) or not isinstance(valor, tipos):
        tipo = "un número entero" if entero else "un número"
        raise ConfigError(f"{_donde(ruta, clave)}: debe ser {tipo}")
    if valor < minimo:
        raise ConfigError(f"{_donde(ruta, clave)}: debe ser como mínimo {minimo}")
    return valor


def lista_textos_opcional(datos: dict[str, Any], clave: str, ruta: str) -> tuple[str, ...]:
    """La clave es opcional; si está, debe ser una lista de textos no vacíos."""
    if clave not in datos:
        return ()
    valor = datos[clave]
    if not isinstance(valor, list) or not all(isinstance(x, str) and x.strip() for x in valor):
        raise ConfigError(f"{_donde(ruta, clave)}: debe ser una lista de textos")
    return tuple(x.strip() for x in valor)


def rechazar_claves_desconocidas(
    datos: dict[str, Any], permitidas: Iterable[str], ruta: str
) -> None:
    """Detecta claves que no existen (casi siempre, erratas).

    Sin esto, escribir "extensions" en vez de "extensiones" se ignoraría en
    silencio y la acción afectaría a TODOS los ficheros. Se sugiere la clave
    más parecida para que el arreglo sea inmediato.
    """
    validas = sorted(set(permitidas))
    for clave in datos:
        if clave not in validas:
            parecidas = difflib.get_close_matches(clave, validas, n=1)
            sugerencia = f" ¿Quisiste decir '{parecidas[0]}'?" if parecidas else ""
            raise ConfigError(
                f"{ruta}: la clave '{clave}' no existe.{sugerencia} "
                f"Claves válidas: {', '.join(validas)}"
            )
