"""Utilidades compartidas por todas las pruebas (pytest las carga solo).

Principio de las pruebas: NUNCA tocan ficheros reales. Todo ocurre dentro de
``tmp_path``, una carpeta temporal única que pytest crea y borra por prueba.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from tareas.errores import SinRedError
from tareas.ia import ProveedorIA, VAR_CLAVE, VAR_MODELO, VAR_URL


@pytest.fixture(autouse=True)
def entorno_aislado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Se aplica a TODAS las pruebas (autouse) para que sean reproducibles.

    - Borra las variables de IA: ninguna prueba debe depender de tu .env real.
    - Cambia la carpeta actual a una temporal: así tampoco se lee un .env
      ni un acciones.json de verdad.
    """
    for variable in (VAR_URL, VAR_MODELO, VAR_CLAVE, "TAREAS_CONFIG", "TAREAS_DEBUG"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def carpeta(tmp_path: Path) -> Path:
    """Carpeta de trabajo vacía, como ~/pruebas-tareas."""
    destino = tmp_path / "pruebas"
    destino.mkdir()
    return destino


def crear_fichero(carpeta: Path, nombre: str, contenido: str | bytes = "x", dias: float = 0) -> Path:
    """Crea un fichero y, si ``dias`` > 0, lo «envejece» ese número de días.

    ``os.utime`` cambia la fecha de modificación: así se prueban los filtros
    de antigüedad sin esperar 30 días de verdad.
    """
    ruta = carpeta / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(contenido, bytes):
        ruta.write_bytes(contenido)
    else:
        ruta.write_text(contenido, encoding="utf-8")
    if dias:
        instante = time.time() - dias * 86400
        os.utime(ruta, (instante, instante))
    return ruta


def escribir_config(ruta: Path, acciones: list[dict[str, Any]], version: int = 1) -> Path:
    """Escribe un acciones.json de prueba y devuelve su ruta."""
    ruta.write_text(
        json.dumps({"version": version, "acciones": acciones}, ensure_ascii=False), encoding="utf-8"
    )
    return ruta


class IAFalsa(ProveedorIA):
    """IA de pega: responde lo que le digamos, sin red. Registra las llamadas."""

    def __init__(self, respuesta: str = "Resumen de prueba.") -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[str, str]] = []

    @property
    def descripcion(self) -> str:
        return "IA falsa"

    def consultar(self, instruccion: str, texto: str) -> str:
        self.llamadas.append((instruccion, texto))
        return self.respuesta


class IASinRed(ProveedorIA):
    """IA que siempre falla como si no hubiera conexión."""

    @property
    def descripcion(self) -> str:
        return "IA sin red"

    def consultar(self, instruccion: str, texto: str) -> str:
        raise SinRedError("No puedo conectar con el servidor de IA (prueba).")
