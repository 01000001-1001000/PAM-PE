"""Las ACCIONES: cada clase sabe PLANIFICAR un tipo de trabajo sobre una carpeta.

Jerarquía de clases::

    Accion                      datos comunes + fábrica desde el JSON
    ├── AccionSimple            añade planificar() (abstracto)
    │   ├── Mover               mover ficheros a otra carpeta
    │   ├── Copiar              copiar ficheros a otra carpeta
    │   ├── Borrar              borrar ficheros (destructiva)
    │   ├── Renombrar           renombrar con una plantilla
    │   ├── OrdenarPorTipo      repartir en subcarpetas por tipo
    │   ├── Duplicados          detectar ficheros con igual contenido
    │   ├── IaResumir           resumir documentos con IA
    │   └── IaRenombrar         renombrar según el contenido (IA)
    └── Cadena                  varias acciones simples seguidas

REGLA DE ORO: una acción NUNCA toca el disco al planificar (solo lee). Devuelve
un ``Plan`` y es el Motor quien lo aplica. Así ``--simular`` es gratis y seguro.

AÑADIR UN TIPO NUEVO no exige tocar nada más: basta crear la subclase con su
atributo ``tipo``; se registra sola (ver ``__init_subclass__``).
"""

from __future__ import annotations

import dataclasses
import re
import string
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from .errores import ConfigError, EjecucionError
from .filtros import Filtro
from .ia import exigir_proveedor
from .lector import es_legible, leer_texto
from .plan import Contexto, Operacion, Plan
from .utilidades import hash_fichero, nombre_libre, sanear_nombre
from .validacion import (
    bool_opcional,
    exigir_texto,
    numero_opcional,
    rechazar_claves_desconocidas,
    texto_opcional,
)

# Los nombres de acción se teclean en la terminal: minúsculas, números y guiones.
_NOMBRE_VALIDO = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


# =============================================================================
# Clase base
# =============================================================================
# frozen=True  -> las acciones son INMUTABLES una vez creadas (no se pueden
#                 modificar por accidente mientras se ejecutan).
# kw_only=True -> los campos solo se pasan por nombre: Mover(nombre="x", ...).
@dataclass(frozen=True, kw_only=True)
class Accion:
    """Datos comunes a todas las acciones y fábrica que las crea desde el JSON."""

    # --- Campos (vienen de acciones.json) ----------------------------------
    nombre: str
    descripcion: str
    origen: Path | None = None  # carpeta de trabajo por defecto (admite ~)
    destino: Path | None = None  # relativo -> se interpreta dentro de la carpeta de trabajo
    filtro: Filtro = field(default_factory=Filtro)
    recursivo: bool = False  # ¿entrar también en subcarpetas?
    confirmar: bool = False  # ¿preguntar antes de aplicar?

    # --- Atributos de CLASE (describen el tipo, no cada instancia) ---------
    tipo: ClassVar[str] = ""  # el valor de "tipo" en el JSON
    requiere_ia: ClassVar[bool] = False
    destructiva: ClassVar[bool] = False  # ¿puede perder datos?
    CLAVES_COMUNES: ClassVar[frozenset[str]] = frozenset(
        {"nombre", "descripcion", "tipo", "origen", "destino", "filtro", "recursivo", "confirmar"}
    )
    # Claves que admite este tipo en el JSON (las subclases amplían el conjunto).
    claves_permitidas: ClassVar[frozenset[str]] = CLAVES_COMUNES
    # Registro tipo -> clase. Lo rellena __init_subclass__.
    _registro: ClassVar[dict[str, type[Accion]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Se ejecuta automáticamente cada vez que se define una subclase.

        Si la subclase declara un ``tipo`` propio, se registra: así la fábrica
        ``desde_dict`` encuentra la clase correcta sin ``if/elif`` gigantes.
        """
        super().__init_subclass__(**kwargs)
        tipo = cls.__dict__.get("tipo")
        if tipo:
            Accion._registro[tipo] = cls

    # --- Propiedades -------------------------------------------------------
    @property
    def es_destructiva(self) -> bool:
        """Las subclases pueden decidirlo por instancia (ver Duplicados)."""
        return self.destructiva

    @property
    def requiere_confirmacion(self) -> bool:
        return self.confirmar

    @staticmethod
    def tipos_disponibles() -> list[str]:
        """Nombres de tipo registrados, para mensajes de ayuda."""
        return sorted(Accion._registro)

    # ------------------------------------------------------------------
    # FÁBRICA ESTÁTICA PRINCIPAL: JSON (dict) -> objeto Accion validado.
    # ------------------------------------------------------------------
    @staticmethod
    def desde_dict(datos: Any, indice: int) -> Accion:
        """Crea la Accion correcta según el campo ``tipo``.

        Args:
            datos:  el dict de la acción tal como se leyó del JSON (no se fía).
            indice: posición en la lista "acciones" (para localizar errores).
        Raises:
            ConfigError: indicando la ruta exacta del campo que falla.
        """
        ruta = f"acciones[{indice}]"
        if not isinstance(datos, dict):
            raise ConfigError(f"{ruta}: cada acción debe ser un objeto JSON {{...}}")

        nombre = exigir_texto(datos, "nombre", ruta)
        ruta = f"{ruta} ('{nombre}')"  # a partir de aquí los mensajes citan el nombre
        if not _NOMBRE_VALIDO.match(nombre):
            raise ConfigError(
                f"{ruta}.nombre: usa solo minúsculas, números y guiones (p. ej. 'ordenar-descargas')"
            )

        tipo = exigir_texto(datos, "tipo", ruta)
        clase = Accion._registro.get(tipo)
        if clase is None:
            raise ConfigError(
                f"{ruta}.tipo: el tipo '{tipo}' no existe. "
                f"Tipos válidos: {', '.join(Accion.tipos_disponibles())}"
            )

        rechazar_claves_desconocidas(datos, clase.claves_permitidas, ruta)
        return clase._desde_dict(datos, ruta)

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Accion:
        """Construcción por defecto: solo campos comunes. Las subclases con
        campos propios lo redefinen (y llaman a ``_campos_comunes``)."""
        return cls(**cls._campos_comunes(datos, ruta))

    @classmethod
    def _campos_comunes(
        cls, datos: dict[str, Any], ruta: str, *, confirmar_defecto: bool = False
    ) -> dict[str, Any]:
        """Lee y valida los campos que comparten todas las acciones."""
        origen = texto_opcional(datos, "origen", ruta)
        destino = texto_opcional(datos, "destino", ruta)
        return {
            "nombre": datos["nombre"].strip(),
            "descripcion": exigir_texto(datos, "descripcion", ruta),
            # expanduser(): convierte «~» en la carpeta personal. La shell lo
            # hace por nosotros en la terminal, pero NO dentro de un JSON.
            "origen": None if origen is None else Path(origen).expanduser(),
            "destino": None if destino is None else Path(destino).expanduser(),
            "filtro": Filtro.desde_dict(datos["filtro"], ruta) if "filtro" in datos else Filtro(),
            "recursivo": bool_opcional(datos, "recursivo", ruta, False),
            "confirmar": bool_opcional(datos, "confirmar", ruta, confirmar_defecto),
        }

    @staticmethod
    def _exigir_destino(datos: dict[str, Any], ruta: str, tipo: str) -> None:
        """Comprueba que el JSON trae ``destino`` (obligatorio en ciertos tipos)."""
        if "destino" not in datos:
            raise ConfigError(f"{ruta}: las acciones de tipo '{tipo}' necesitan la clave 'destino'")


# =============================================================================
# Acciones «simples»: las que planifican operaciones sobre ficheros
# =============================================================================
@dataclass(frozen=True, kw_only=True)
class AccionSimple(Accion, ABC):
    """Una acción que sabe planificar sobre una carpeta. Abstracta: no se
    puede instanciar, solo sus subclases (obliga a implementar ``planificar``)."""

    @abstractmethod
    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        """Decide qué operaciones haría sobre ``carpeta``. NO modifica el disco."""

    # --- Utilidades compartidas por las subclases --------------------------
    def _carpeta_destino(self, carpeta: Path) -> Path | None:
        """Resuelve ``destino``: absoluto tal cual; relativo, dentro de ``carpeta``."""
        if self.destino is None:
            return None
        return self.destino if self.destino.is_absolute() else carpeta / self.destino

    def _candidatos(self, carpeta: Path, ctx: Contexto, avisos: list[str]) -> list[Path]:
        """Ficheros de ``carpeta`` que cumplen el filtro, en orden estable.

        - Ignora carpetas, enlaces simbólicos y ficheros ocultos (.env, .DS_Store...).
        - Si es recursiva, no vuelve a entrar en la carpeta de destino.
        """
        destino = self._carpeta_destino(carpeta)
        entradas = carpeta.rglob("*") if self.recursivo else carpeta.iterdir()
        encontrados: list[Path] = []
        try:
            for ruta in entradas:
                partes = ruta.relative_to(carpeta).parts
                if any(p.startswith(".") for p in partes):  # oculto (o dentro de una carpeta oculta)
                    continue
                # No procesar enlaces simbólicos (podrían apuntar fuera de la carpeta).
                if ruta.is_symlink() or not ruta.is_file():
                    continue
                if destino is not None and destino != carpeta and destino in ruta.parents:
                    continue  # ya está dentro del destino
                try:
                    if self.filtro.coincide(ruta, ctx.ahora):
                        encontrados.append(ruta)
                except OSError as error:  # un fichero ilegible no debe tumbar el resto
                    avisos.append(f"Se ignora '{ruta.name}': {error.strerror or error}")
        except OSError as error:
            raise EjecucionError(
                f"No puedo leer la carpeta '{carpeta}': {error.strerror or error}"
            ) from None
        # Orden determinista (sin distinguir mayúsculas): mismas entradas -> mismo plan.
        return sorted(encontrados, key=lambda p: str(p).casefold())


@dataclass(frozen=True, kw_only=True)
class Mover(AccionSimple):
    """Mueve los ficheros que cumplan el filtro a ``destino``."""

    tipo = "mover"

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Mover:
        cls._exigir_destino(datos, ruta, cls.tipo)
        return cls(**cls._campos_comunes(datos, ruta))

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        destino = self._carpeta_destino(carpeta)
        assert destino is not None  # lo garantiza _desde_dict (aserción de desarrollo)
        reservados: set[str] = set()
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            if fichero.parent.resolve() == destino.resolve():
                continue  # ya está en su sitio
            # nombre_libre evita sobrescribir si ya existe un fichero con ese nombre.
            plan.operaciones.append(
                Operacion("mover", fichero, nombre_libre(destino / fichero.name, reservados))
            )
        return plan


@dataclass(frozen=True, kw_only=True)
class Copiar(AccionSimple):
    """Copia los ficheros que cumplan el filtro a ``destino`` (copia de seguridad)."""

    tipo = "copiar"

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Copiar:
        cls._exigir_destino(datos, ruta, cls.tipo)
        return cls(**cls._campos_comunes(datos, ruta))

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        destino = self._carpeta_destino(carpeta)
        assert destino is not None
        reservados: set[str] = set()
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            plan.operaciones.append(
                Operacion("copiar", fichero, nombre_libre(destino / fichero.name, reservados))
            )
        return plan


@dataclass(frozen=True, kw_only=True)
class Borrar(AccionSimple):
    """Borra los ficheros que cumplan el filtro. DESTRUCTIVA: por defecto pide confirmación."""

    tipo = "borrar"
    destructiva = True

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Borrar:
        # confirmar_defecto=True: si no dices nada, SIEMPRE pregunta antes de borrar.
        comunes = cls._campos_comunes(datos, ruta, confirmar_defecto=True)
        # Seguridad: un filtro vacío borraría TODOS los ficheros de la carpeta.
        if comunes["filtro"].vacio:
            raise ConfigError(
                f"{ruta}.filtro: una acción que borra necesita al menos una condición "
                "(extensiones, patron, mas_antiguo_que_dias o mayor_que_mb)"
            )
        return cls(**comunes)

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            plan.operaciones.append(Operacion("borrar", fichero))
        return plan


# Parámetros permitidos en la plantilla de «renombrar»: {fecha}, {n}, {ext}, {nombre}.
_CAMPOS_PLANTILLA = frozenset({"fecha", "n", "ext", "nombre"})


@dataclass(frozen=True, kw_only=True)
class Renombrar(AccionSimple):
    """Renombra con una plantilla, p. ej. ``{fecha:%Y-%m-%d}_{n:03}{ext}``.

    Campos de la plantilla:
        {fecha:FORMATO}  fecha de modificación (formato strftime: %Y-%m-%d)
        {n:03}           contador 1, 2, 3... (el ``03`` rellena con ceros)
        {ext}            extensión original con punto (.jpg)
        {nombre}         nombre original sin extensión
    """

    tipo = "renombrar"
    claves_permitidas = Accion.CLAVES_COMUNES | {"plantilla"}

    plantilla: str

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Renombrar:
        plantilla = exigir_texto(datos, "plantilla", ruta)
        cls._validar_plantilla(plantilla, f"{ruta}.plantilla")
        return cls(**cls._campos_comunes(datos, ruta), plantilla=plantilla)

    @staticmethod
    def _validar_plantilla(plantilla: str, ruta: str) -> None:
        """Comprueba la plantilla al CARGAR la configuración (no al ejecutar)."""
        try:
            # Formatter().parse() separa el texto en (literal, campo, formato, conversión).
            campos = [c for _, c, _, _ in string.Formatter().parse(plantilla) if c is not None]
        except ValueError as error:
            raise ConfigError(f"{ruta}: llaves mal cerradas ({error})") from None
        for campo in campos:
            # Se compara el nombre COMPLETO: así se rechazan cosas como {fecha.__class__}.
            if campo not in _CAMPOS_PLANTILLA:
                raise ConfigError(
                    f"{ruta}: el campo '{{{campo}}}' no existe. "
                    f"Campos válidos: {', '.join('{' + c + '}' for c in sorted(_CAMPOS_PLANTILLA))}"
                )
        try:
            # Prueba real con datos de ejemplo: detecta formatos de fecha/número inválidos.
            ejemplo = plantilla.format(fecha=datetime(2026, 1, 2), n=1, ext=".jpg", nombre="foto")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise ConfigError(f"{ruta}: formato inválido ({error})") from None
        if not ejemplo.strip() or any(c in ejemplo for c in '/\\:*?"<>|'):
            raise ConfigError(
                f"{ruta}: el nombre resultante no puede estar vacío ni contener / \\ : * ? \" < > |"
            )

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        # Se numera en orden cronológico (y por nombre en caso de empate).
        fechas: dict[Path, float] = {}
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            try:
                fechas[fichero] = fichero.stat().st_mtime
            except OSError as error:
                plan.avisos.append(f"Se ignora '{fichero.name}': {error.strerror or error}")
        reservados: set[str] = set()
        ordenados = sorted(fechas, key=lambda p: (fechas[p], p.name.casefold()))
        for n, fichero in enumerate(ordenados, start=1):
            nuevo = self.plantilla.format(
                fecha=datetime.fromtimestamp(fechas[fichero]),
                n=n,
                ext=fichero.suffix,
                nombre=fichero.stem,
            )
            if nuevo == fichero.name:
                continue  # ya se llama así: nada que hacer (hace la acción idempotente)
            plan.operaciones.append(
                Operacion("mover", fichero, nombre_libre(fichero.with_name(nuevo), reservados))
            )
        return plan


# Categorías por defecto de «ordenar_por_tipo»: carpeta -> extensiones.
# Sin tildes en los nombres de carpeta, para evitar problemas entre sistemas.
CATEGORIAS_POR_DEFECTO: dict[str, tuple[str, ...]] = {
    "PDF": (".pdf",),
    "Documentos": (".doc", ".docx", ".odt", ".txt", ".md", ".rtf"),
    "Hojas": (".xls", ".xlsx", ".ods", ".csv"),
    "Presentaciones": (".ppt", ".pptx", ".odp"),
    "Imagenes": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"),
    "Audio": (".mp3", ".wav", ".flac", ".ogg", ".m4a"),
    "Video": (".mp4", ".mkv", ".avi", ".mov", ".webm"),
    "Comprimidos": (".zip", ".rar", ".7z", ".tar", ".gz"),
    "Instaladores": (".exe", ".msi", ".deb", ".dmg", ".pkg", ".appimage"),
    "Codigo": (".py", ".js", ".html", ".css", ".java", ".c", ".cpp", ".json"),
}


@dataclass(frozen=True, kw_only=True)
class OrdenarPorTipo(AccionSimple):
    """Reparte los ficheros en subcarpetas según su extensión."""

    tipo = "ordenar_por_tipo"
    claves_permitidas = Accion.CLAVES_COMUNES | {"categorias"}

    # Tupla de pares (carpeta, extensiones): inmutable, a diferencia de un dict.
    categorias: tuple[tuple[str, tuple[str, ...]], ...] = tuple(CATEGORIAS_POR_DEFECTO.items())

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> OrdenarPorTipo:
        comunes = cls._campos_comunes(datos, ruta)
        if "categorias" not in datos:
            return cls(**comunes)
        crudo = datos["categorias"]
        donde = f"{ruta}.categorias"
        if not isinstance(crudo, dict) or not crudo:
            raise ConfigError(f'{donde}: debe ser un objeto, p. ej. {{"Fotos": [".jpg", ".png"]}}')
        categorias = []
        for carpeta, extensiones in crudo.items():
            if not isinstance(extensiones, list) or not all(isinstance(e, str) for e in extensiones):
                raise ConfigError(f"{donde}.{carpeta}: debe ser una lista de extensiones")
            if not carpeta or any(c in carpeta for c in '/\\:*?"<>|'):
                raise ConfigError(f"{donde}: '{carpeta}' no es un nombre de carpeta válido")
            normalizadas = tuple(e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensiones)
            categorias.append((carpeta, normalizadas))
        return cls(**comunes, categorias=tuple(categorias))

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        base = self._carpeta_destino(carpeta) or carpeta
        # Índice inverso extensión -> carpeta, para buscar en O(1).
        por_extension = {ext: nombre for nombre, exts in self.categorias for ext in exts}
        reservados: set[str] = set()
        sin_categoria = 0
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            categoria = por_extension.get(fichero.suffix.lower())
            if categoria is None:
                sin_categoria += 1  # se deja donde está
                continue
            plan.operaciones.append(
                Operacion(
                    "mover", fichero, nombre_libre(base / categoria / fichero.name, reservados)
                )
            )
        if sin_categoria:
            plan.avisos.append(f"{sin_categoria} fichero(s) sin categoría conocida se dejan donde están.")
        return plan


_MODOS_DUPLICADOS = ("informar", "mover", "borrar")


@dataclass(frozen=True, kw_only=True)
class Duplicados(AccionSimple):
    """Detecta ficheros con el MISMO CONTENIDO (mismo hash) aunque se llamen distinto.

    De cada grupo de duplicados se conserva el más antiguo. Los demás se
    informan, se mueven o se borran según ``modo``.
    """

    tipo = "duplicados"
    claves_permitidas = Accion.CLAVES_COMUNES | {"modo"}

    modo: str = "informar"

    @property
    def es_destructiva(self) -> bool:
        # Solo es destructiva si BORRA (en los otros modos no se pierde nada).
        return self.modo == "borrar"

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Duplicados:
        modo = texto_opcional(datos, "modo", ruta) or "informar"
        if modo not in _MODOS_DUPLICADOS:
            raise ConfigError(f"{ruta}.modo: debe ser uno de {', '.join(_MODOS_DUPLICADOS)}")
        if modo == "mover":
            cls._exigir_destino(datos, ruta, "duplicados con modo 'mover'")
        comunes = cls._campos_comunes(datos, ruta, confirmar_defecto=(modo == "borrar"))
        return cls(**comunes, modo=modo)

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        plan = Plan(self.nombre, carpeta)
        # Paso 1: agrupar por TAMAÑO (barato). Dos ficheros de distinto tamaño
        # no pueden ser iguales, así evitamos calcular hashes de casi todo.
        por_tamano: dict[int, list[Path]] = {}
        for fichero in self._candidatos(carpeta, ctx, plan.avisos):
            try:
                tamano = fichero.stat().st_size
            except OSError as error:
                plan.avisos.append(f"Se ignora '{fichero.name}': {error.strerror or error}")
                continue
            if tamano > 0:  # los ficheros vacíos son «iguales» pero no interesan
                por_tamano.setdefault(tamano, []).append(fichero)

        # Paso 2: solo si hay 2+ del mismo tamaño, comparar el hash del contenido.
        por_hash: dict[str, list[Path]] = {}
        for grupo in por_tamano.values():
            if len(grupo) < 2:
                continue
            for fichero in grupo:
                try:
                    por_hash.setdefault(hash_fichero(fichero), []).append(fichero)
                except OSError as error:
                    plan.avisos.append(f"No puedo leer '{fichero.name}': {error.strerror or error}")

        destino = self._carpeta_destino(carpeta)
        reservados: set[str] = set()
        for grupo in por_hash.values():
            if len(grupo) < 2:
                continue
            # Se conserva el más antiguo (y por nombre, si hay empate).
            grupo.sort(key=lambda p: (p.stat().st_mtime, p.name.casefold()))
            original, *copias = grupo
            for copia in copias:
                nota = f"duplicado de '{original.name}'"
                if self.modo == "borrar":
                    plan.operaciones.append(Operacion("borrar", copia, nota=nota))
                elif self.modo == "mover":
                    assert destino is not None
                    plan.operaciones.append(
                        Operacion("mover", copia, nombre_libre(destino / copia.name, reservados), nota=nota)
                    )
                else:  # "informar": solo se muestra
                    plan.operaciones.append(Operacion("info", copia, nota=nota))
        plan.operaciones.sort(key=lambda op: str(op.origen).casefold())
        return plan


# =============================================================================
# Acciones con IA
# =============================================================================
_INSTRUCCION_RESUMIR = (
    "Eres un asistente que resume documentos. Escribe en español un resumen claro "
    "de 5 a 8 líneas con las ideas principales. Usa Markdown simple (viñetas si ayudan). "
    "No inventes datos que no aparezcan en el texto."
)
_INSTRUCCION_NOMBRAR = (
    "Eres un asistente que pone nombre a ficheros. Lee el comienzo del documento y "
    "responde SOLO con un nombre de fichero corto: de 3 a 6 palabras en minúsculas "
    "separadas por guiones, sin extensión, sin comillas y sin ninguna explicación."
)


class _IaMixin:
    """Utilidades compartidas por las acciones con IA (mixin: se «mezcla» en
    las clases que lo necesitan; no tiene sentido por sí solo)."""

    @staticmethod
    def _leibles(candidatos: list[Path], avisos: list[str]) -> list[Path]:
        """Se queda con los ficheros de los que sabemos extraer texto."""
        legibles = [c for c in candidatos if es_legible(c) and not c.name.endswith(".resumen.md")]
        ignorados = len(candidatos) - len(legibles)
        if ignorados:
            avisos.append(f"{ignorados} fichero(s) ignorados: la IA solo lee PDF y texto.")
        return legibles


@dataclass(frozen=True, kw_only=True)
class IaResumir(_IaMixin, AccionSimple):
    """Resume cada documento con IA y guarda el resumen en ``<fichero>.resumen.md``."""

    tipo = "ia_resumir"
    requiere_ia = True
    claves_permitidas = Accion.CLAVES_COMUNES | {"max_caracteres", "instruccion"}

    max_caracteres: int = 6000
    instruccion: str = _INSTRUCCION_RESUMIR

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> IaResumir:
        extra: dict[str, Any] = {}
        maximo = numero_opcional(datos, "max_caracteres", ruta, entero=True, minimo=100)
        if maximo is not None:
            extra["max_caracteres"] = maximo
        instruccion = texto_opcional(datos, "instruccion", ruta)
        if instruccion is not None:
            extra["instruccion"] = instruccion
        return cls(**cls._campos_comunes(datos, ruta), **extra)

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        ia = exigir_proveedor(ctx.ia)  # IANoDisponible si no hay IA configurada
        plan = Plan(self.nombre, carpeta)
        salida_dir = self._carpeta_destino(carpeta)
        for fichero in self._leibles(self._candidatos(carpeta, ctx, plan.avisos), plan.avisos):
            salida = (salida_dir or fichero.parent) / f"{fichero.name}.resumen.md"
            if salida.exists():
                plan.avisos.append(f"'{fichero.name}' ya tiene resumen; se omite.")
                continue
            try:
                texto = leer_texto(fichero, self.max_caracteres)
            except EjecucionError as error:
                plan.avisos.append(error.mensaje)  # un PDF roto no detiene a los demás
                continue
            if not texto.strip():
                plan.avisos.append(f"'{fichero.name}' no tiene texto extraíble; se omite.")
                continue
            # Si falla la red aquí, SinRedError sube al motor y NO se aplica nada.
            resumen = ia.consultar(self.instruccion, texto)
            contenido = (
                f"# Resumen de {fichero.name}\n\n{resumen}\n\n---\n"
                f"_Generado con IA el {ctx.ahora:%Y-%m-%d}. Revísalo antes de fiarte._\n"
            )
            plan.operaciones.append(
                Operacion("escribir", fichero, salida, contenido=contenido, nota="resumen generado por IA")
            )
        return plan


@dataclass(frozen=True, kw_only=True)
class IaRenombrar(_IaMixin, AccionSimple):
    """La IA lee el principio de cada documento y propone un nombre descriptivo."""

    tipo = "ia_renombrar"
    requiere_ia = True
    claves_permitidas = Accion.CLAVES_COMUNES | {"max_caracteres"}

    max_caracteres: int = 1500

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> IaRenombrar:
        extra: dict[str, Any] = {}
        maximo = numero_opcional(datos, "max_caracteres", ruta, entero=True, minimo=100)
        if maximo is not None:
            extra["max_caracteres"] = maximo
        return cls(**cls._campos_comunes(datos, ruta), **extra)

    def planificar(self, carpeta: Path, ctx: Contexto) -> Plan:
        ia = exigir_proveedor(ctx.ia)
        plan = Plan(self.nombre, carpeta)
        reservados: set[str] = set()
        for fichero in self._leibles(self._candidatos(carpeta, ctx, plan.avisos), plan.avisos):
            try:
                texto = leer_texto(fichero, self.max_caracteres)
            except EjecucionError as error:
                plan.avisos.append(error.mensaje)
                continue
            if not texto.strip():
                plan.avisos.append(f"'{fichero.name}' no tiene texto extraíble; se omite.")
                continue
            respuesta = ia.consultar(_INSTRUCCION_NOMBRAR, texto)
            # NUNCA se usa tal cual lo que devuelve la IA: se toma la primera
            # línea, se quita una posible extensión y se «sanea» (sin / .. ni
            # caracteres raros). Podría devolver cualquier cosa.
            primera_linea = (respuesta.strip().splitlines() or [""])[0]
            # Los modelos suelen envolver el nombre en comillas, comillas
            # invertidas o negritas de Markdown ("informe.txt", `informe`, **informe**).
            # Se quitan ANTES de buscar la extensión, que si no no estaría al final.
            desenvuelta = primera_linea.strip().strip("\"'`*_ \t")
            sin_extension = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", desenvuelta)
            nombre = sanear_nombre(sin_extension)
            if not nombre:
                plan.avisos.append(f"La IA no propuso un nombre válido para '{fichero.name}'.")
                continue
            nuevo = fichero.with_name(f"{nombre}{fichero.suffix.lower()}")
            if nuevo.name == fichero.name:
                continue
            plan.operaciones.append(
                Operacion(
                    "mover", fichero, nombre_libre(nuevo, reservados), nota="nombre propuesto por IA"
                )
            )
        return plan


# =============================================================================
# Cadena: varias acciones seguidas
# =============================================================================
@dataclass(frozen=True, kw_only=True)
class Cadena(Accion):
    """Ejecuta otras acciones, una tras otra, con una sola orden.

    No planifica por sí misma: el Motor ejecuta cada paso (planificar -> aplicar)
    antes de pasar al siguiente, porque el paso 2 debe ver el resultado del paso 1.
    """

    tipo = "cadena"
    claves_permitidas = frozenset({"nombre", "descripcion", "tipo", "origen", "pasos"})

    pasos: tuple[str, ...]  # nombres tal como aparecen en el JSON
    pasos_resueltos: tuple[AccionSimple, ...] = ()  # objetos reales, tras enlazar()

    @property
    def requiere_confirmacion(self) -> bool:
        return any(p.requiere_confirmacion for p in self.pasos_resueltos)

    @property
    def es_destructiva(self) -> bool:
        return any(p.es_destructiva for p in self.pasos_resueltos)

    @classmethod
    def _desde_dict(cls, datos: dict[str, Any], ruta: str) -> Cadena:
        pasos = datos.get("pasos")
        if not isinstance(pasos, list) or not pasos or not all(isinstance(p, str) for p in pasos):
            raise ConfigError(f"{ruta}.pasos: debe ser una lista no vacía con nombres de acciones")
        origen = texto_opcional(datos, "origen", ruta)
        return cls(
            nombre=datos["nombre"].strip(),
            descripcion=exigir_texto(datos, "descripcion", ruta),
            origen=None if origen is None else Path(origen).expanduser(),
            pasos=tuple(pasos),
        )

    def enlazar(self, por_nombre: Mapping[str, Accion]) -> Cadena:
        """Sustituye los nombres de ``pasos`` por las acciones reales.

        Se hace DESPUÉS de crear todas las acciones (una cadena puede citar
        acciones definidas más abajo en el fichero). Como la clase es
        inmutable, devuelve una copia nueva con ``dataclasses.replace``.
        """
        resueltos: list[AccionSimple] = []
        for nombre in self.pasos:
            paso = por_nombre.get(nombre)
            donde = f"acciones ('{self.nombre}').pasos"
            if paso is None:
                raise ConfigError(f"{donde}: la acción '{nombre}' no existe")
            if not isinstance(paso, AccionSimple):
                raise ConfigError(f"{donde}: '{nombre}' es otra cadena (no se permiten cadenas anidadas)")
            resueltos.append(paso)
        return dataclasses.replace(self, pasos_resueltos=tuple(resueltos))
