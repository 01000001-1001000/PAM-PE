"""Filtros: deciden a QUÉ ficheros afecta una acción.

Un ``Filtro`` es un objeto inmutable creado a partir del bloque ``"filtro"``
de acciones.json. Todas las condiciones que se indiquen se combinan con «Y»:
un fichero debe cumplirlas todas. Un filtro sin condiciones acepta todo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from .errores import ConfigError
from .validacion import (
    lista_textos_opcional,
    numero_opcional,
    rechazar_claves_desconocidas,
    texto_opcional,
)


# frozen=True: una vez creado, el filtro no se puede modificar (más seguro).
@dataclass(frozen=True)
class Filtro:
    """Condiciones que debe cumplir un fichero para ser procesado."""

    # Extensiones en minúsculas y con punto: (".pdf", ".docx"). Vacío = cualquiera.
    extensiones: tuple[str, ...] = ()
    # Expresión regular ya compilada que se busca en el NOMBRE del fichero.
    patron: re.Pattern[str] | None = None
    # Solo ficheros modificados hace MÁS de estos días.
    mas_antiguo_que_dias: int | None = None
    # Solo ficheros de MÁS de estos megabytes.
    mayor_que_mb: float | None = None

    # ClassVar: pertenece a la clase, no a cada instancia (no es un campo).
    CLAVES: ClassVar[frozenset[str]] = frozenset(
        {"extensiones", "patron", "mas_antiguo_que_dias", "mayor_que_mb"}
    )

    @property
    def vacio(self) -> bool:
        """True si no impone ninguna condición (aceptaría todos los ficheros)."""
        return (
            not self.extensiones
            and self.patron is None
            and self.mas_antiguo_que_dias is None
            and self.mayor_que_mb is None
        )

    # ------------------------------------------------------------------
    # FÁBRICA estática: crea un Filtro validado a partir del JSON.
    # Es estático porque no necesita ninguna instancia previa: construye una.
    # ------------------------------------------------------------------
    @staticmethod
    def desde_dict(datos: Any, ruta: str) -> Filtro:
        """Construye un Filtro desde el bloque ``filtro`` del JSON.

        Args:
            datos: lo que haya en el JSON bajo "filtro" (puede ser basura).
            ruta:  dónde estamos, para los mensajes de error.
        Raises:
            ConfigError: si algún campo no es válido (indica cuál).
        """
        ruta = f"{ruta}.filtro"
        if not isinstance(datos, dict):
            raise ConfigError(f"{ruta}: debe ser un objeto JSON, p. ej. {{\"extensiones\": [\".pdf\"]}}")
        rechazar_claves_desconocidas(datos, Filtro.CLAVES, ruta)

        # Normalización: ".PDF", "PDF" y ".pdf" significan lo mismo.
        extensiones = tuple(
            e.lower() if e.startswith(".") else f".{e.lower()}"
            for e in lista_textos_opcional(datos, "extensiones", ruta)
        )

        patron_texto = texto_opcional(datos, "patron", ruta)
        patron = None
        if patron_texto is not None:
            try:
                patron = re.compile(patron_texto)
            except re.error as error:
                # Se explica DÓNDE falla la expresión regular.
                raise ConfigError(
                    f"{ruta}.patron: expresión regular inválida ({error.msg}"
                    f"{'' if error.pos is None else f', posición {error.pos}'})"
                ) from None

        dias = numero_opcional(datos, "mas_antiguo_que_dias", ruta, entero=True)
        megas = numero_opcional(datos, "mayor_que_mb", ruta, entero=False)
        return Filtro(extensiones, patron, dias, megas)

    def coincide(self, ruta: Path, ahora: datetime) -> bool:
        """¿Debe procesarse este fichero?

        Args:
            ruta:  fichero a evaluar.
            ahora: instante actual (se inyecta para poder probar con fechas falsas).
        """
        # 1) Extensión (comparada en minúsculas).
        if self.extensiones and ruta.suffix.lower() not in self.extensiones:
            return False
        # 2) Patrón sobre el nombre (search: puede coincidir en cualquier parte).
        if self.patron is not None and not self.patron.search(ruta.name):
            return False
        # 3 y 4) Condiciones que necesitan consultar al sistema de ficheros.
        if self.mas_antiguo_que_dias is not None or self.mayor_que_mb is not None:
            estado = ruta.stat()  # puede lanzar OSError: la acción lo captura
            if self.mas_antiguo_que_dias is not None:
                segundos = ahora.timestamp() - estado.st_mtime
                if segundos <= self.mas_antiguo_que_dias * 86400:  # 86400 s = 1 día
                    return False
            if self.mayor_que_mb is not None and estado.st_size <= self.mayor_que_mb * 1024 * 1024:
                return False
        return True
