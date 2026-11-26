"""Estructuras de datos que viajan entre acciones, motor e interfaz.

El flujo de trabajo de toda la herramienta es:

    Accion.planificar()  ->  Plan (lista de Operaciones, sin tocar el disco)
    Motor.ejecutar()     ->  muestra el Plan, pide confirmación y lo APLICA
                         ->  Informe (qué se hizo, qué falló)

Separar «planificar» de «aplicar» es lo que permite ``--simular`` (enseñar el
plan sin aplicarlo) y las confirmaciones antes de borrar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # solo para los tipos; evita importaciones circulares en ejecución
    from .ia import ProveedorIA

# Tipos de operación posibles. «info» no cambia nada: solo informa (p. ej. un
# duplicado detectado en modo "informar").
TIPOS_OPERACION = ("mover", "copiar", "borrar", "escribir", "info")


@dataclass(frozen=True)
class Operacion:
    """Un cambio concreto y atómico sobre el disco."""

    tipo: str
    origen: Path | None = None
    destino: Path | None = None
    contenido: str | None = None  # solo para "escribir"
    nota: str = ""  # explicación legible (p. ej. «nombre propuesto por IA»)

    def __post_init__(self) -> None:
        # ASERCIONES de desarrollo: comprueban que NOSOTROS (los programadores)
        # construimos operaciones coherentes. No validan datos del usuario (eso
        # lo hacen las excepciones). Con `python -O` se desactivan.
        assert self.tipo in TIPOS_OPERACION, f"tipo de operación desconocido: {self.tipo}"
        if self.tipo in ("mover", "copiar"):
            assert self.origen is not None and self.destino is not None
        if self.tipo == "borrar":
            assert self.origen is not None
        if self.tipo == "escribir":
            assert self.destino is not None and self.contenido is not None

    def a_dict(self) -> dict[str, Any]:
        """Versión serializable a JSON (para ``--json``)."""
        return {
            "tipo": self.tipo,
            "origen": None if self.origen is None else str(self.origen),
            "destino": None if self.destino is None else str(self.destino),
            "nota": self.nota,
        }


@dataclass
class Plan:
    """Lo que una acción PROPONE hacer sobre una carpeta (aún sin hacerlo)."""

    accion: str
    carpeta: Path
    operaciones: list[Operacion] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def reales(self) -> list[Operacion]:
        """Operaciones que de verdad modifican algo (excluye las «info»)."""
        return [op for op in self.operaciones if op.tipo != "info"]

    def a_dict(self) -> dict[str, Any]:
        return {
            "accion": self.accion,
            "carpeta": str(self.carpeta),
            "operaciones": [op.a_dict() for op in self.operaciones],
            "avisos": list(self.avisos),
        }


@dataclass
class Informe:
    """Resultado de ejecutar (o simular) una acción."""

    accion: str
    simulado: bool = False
    previstas: int = 0  # operaciones reales que contenía el plan
    aplicadas: int = 0  # operaciones que se llevaron a cabo con éxito
    fallos: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    omitido: str | None = None  # motivo si se saltó (p. ej. IA no disponible)
    cancelado: bool = False
    pasos: list[Informe] = field(default_factory=list)  # solo en cadenas

    @property
    def ok(self) -> bool:
        """True si todo fue bien. Un paso OMITIDO por falta de IA no es un fallo
        (es justo el «modo sin red»: se explica y se sigue)."""
        return not self.fallos and not self.cancelado and all(p.ok for p in self.pasos)

    def a_dict(self) -> dict[str, Any]:
        return {
            "accion": self.accion,
            "ok": self.ok,
            "simulado": self.simulado,
            "previstas": self.previstas,
            "aplicadas": self.aplicadas,
            "fallos": list(self.fallos),
            "avisos": list(self.avisos),
            "omitido": self.omitido,
            "cancelado": self.cancelado,
            "pasos": [p.a_dict() for p in self.pasos],
        }


@dataclass(frozen=True)
class Contexto:
    """Dependencias que el motor entrega a cada acción al planificar.

    Pasarlas así (en vez de que cada acción las busque por su cuenta) permite
    probar con una IA falsa y un reloj falso sin tocar nada más.
    """

    ia: ProveedorIA | None
    ahora: datetime
