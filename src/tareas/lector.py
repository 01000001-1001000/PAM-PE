"""Lee el TEXTO de un fichero para pasárselo a la IA.

Solo se lee el principio (``max_caracteres``): basta para resumir o nombrar un
documento y evita mandar un PDF de 500 páginas al modelo.
"""

from __future__ import annotations

from pathlib import Path

from .errores import EjecucionError

# Extensiones que sabemos convertir a texto.
EXTENSIONES_TEXTO = frozenset({".txt", ".md", ".csv", ".json", ".log", ".rst", ".py"})
EXTENSIONES_LEIBLES = EXTENSIONES_TEXTO | {".pdf"}


def es_legible(ruta: Path) -> bool:
    """¿Sabemos extraer texto de este tipo de fichero?"""
    return ruta.suffix.lower() in EXTENSIONES_LEIBLES


def leer_texto(ruta: Path, max_caracteres: int) -> str:
    """Devuelve como mucho ``max_caracteres`` caracteres de texto del fichero.

    Raises:
        EjecucionError: el fichero no se puede abrir, está dañado o protegido.
    """
    try:
        if ruta.suffix.lower() == ".pdf":
            return _leer_pdf(ruta, max_caracteres)
        # errors="replace": un byte raro no debe tumbar la lectura (se sustituye por «�»).
        with ruta.open("r", encoding="utf-8", errors="replace") as fichero:
            return fichero.read(max_caracteres)
    except EjecucionError:
        raise
    except OSError as error:
        raise EjecucionError(f"No puedo leer '{ruta.name}': {error.strerror or error}") from None


def _leer_pdf(ruta: Path, max_caracteres: int) -> str:
    """Extrae texto de un PDF página a página hasta alcanzar el límite."""
    # Importación PEREZOSA: pypdf solo se carga si de verdad hay un PDF.
    # Así `tareas --help` y el resto de órdenes arrancan más rápido.
    from pypdf import PdfReader

    trozos: list[str] = []
    total = 0
    try:
        lector = PdfReader(str(ruta))
        for pagina in lector.pages:
            texto = pagina.extract_text() or ""
            trozos.append(texto)
            total += len(texto)
            if total >= max_caracteres:
                break
    except Exception as error:  # noqa: BLE001
        # pypdf puede lanzar muchos tipos de error según cómo esté roto el PDF
        # (cifrado, truncado, estructura inválida...). Todos significan lo mismo
        # para la persona: «no puedo leer este PDF».
        raise EjecucionError(
            f"No puedo leer el PDF '{ruta.name}' (¿está dañado, cifrado o es una imagen escaneada?): "
            f"{type(error).__name__}"
        ) from None
    return "\n".join(trozos)[:max_caracteres]
