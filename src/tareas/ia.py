"""Capa de IA: habla con un servidor de modelos y degrada con elegancia.

Diseño:

* ``ProveedorIA`` es una clase ABSTRACTA: define QUÉ se espera de un proveedor
  (``consultar``) sin decir cómo. Las acciones solo conocen esta interfaz, de
  modo que en las pruebas se sustituye por una IA falsa sin tocar la red.
* ``ProveedorOpenAI`` es la implementación real: cualquier servidor con la
  API «chat/completions» (los modelos del centro, Ollama, etc.). Usa solo la
  librería estándar (urllib), sin dependencias extra.
* Seguridad: la clave se lee de variables de entorno / .env, JAMÁS del código,
  y nunca se escribe en mensajes de error.
* MODO SIN RED: si no hay red o falta la configuración se lanza una excepción
  propia (``SinRedError`` / ``IANoDisponible``) y el motor explica la situación
  y sigue ofreciendo las acciones que no necesitan IA.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Mapping

from dotenv import find_dotenv, load_dotenv

from .errores import IAError, IANoDisponible, SinRedError

# Nombres de las variables de entorno que configuran la IA.
VAR_URL = "TAREAS_IA_URL"
VAR_MODELO = "TAREAS_IA_MODELO"
VAR_CLAVE = "TAREAS_IA_CLAVE"


def cargar_entorno() -> None:
    """Carga el fichero .env (si existe) en las variables de entorno.

    ``find_dotenv(usecwd=True)`` busca .env en la carpeta actual y sus
    superiores. Por defecto ``load_dotenv`` NO pisa variables que ya estén
    definidas en el sistema: lo que exportes en tu shell manda sobre el .env.
    """
    ruta = find_dotenv(usecwd=True)
    if ruta:
        load_dotenv(ruta, encoding="utf-8")


class ProveedorIA(ABC):
    """Contrato mínimo de un proveedor de IA."""

    @abstractmethod
    def consultar(self, instruccion: str, texto: str) -> str:
        """Envía una ``instruccion`` (qué hacer) y un ``texto`` (sobre qué)
        y devuelve la respuesta del modelo como texto.

        Raises:
            SinRedError: no hay conexión con el servidor.
            IAError: el servidor respondió con un error o algo ilegible.
        """

    @property
    @abstractmethod
    def descripcion(self) -> str:
        """Texto corto para mostrar (nunca incluye la clave)."""


class ProveedorOpenAI(ProveedorIA):
    """Proveedor para servidores compatibles con la API de OpenAI."""

    def __init__(
        self, url_base: str, modelo: str, clave: str | None = None, tiempo_max: float = 60.0
    ) -> None:
        # Seguridad: urllib también entiende file:// y ftp://. Solo permitimos
        # http(s) para que un .env manipulado no pueda leer ficheros locales.
        if urllib.parse.urlparse(url_base).scheme not in ("http", "https"):
            raise IAError(f"{VAR_URL} debe empezar por http:// o https:// (valor actual: {url_base!r})")
        self._url = url_base.rstrip("/")  # atributos con _ : uso interno de la clase
        self._modelo = modelo
        self._clave = clave or None  # cadena vacía -> sin clave
        self._tiempo_max = tiempo_max

    # ------------------------------------------------------------------
    # FÁBRICA estática: construye el proveedor a partir del entorno, o
    # devuelve None si no está configurado (= IA no disponible).
    # ------------------------------------------------------------------
    @staticmethod
    def desde_entorno(entorno: Mapping[str, str] | None = None) -> ProveedorOpenAI | None:
        """Crea el proveedor con las variables TAREAS_IA_*.

        Args:
            entorno: diccionario de variables; por defecto ``os.environ``
                     (se puede inyectar otro en las pruebas).
        Returns:
            El proveedor, o ``None`` si faltan URL o modelo.
        """
        entorno = os.environ if entorno is None else entorno
        url = entorno.get(VAR_URL, "").strip()
        modelo = entorno.get(VAR_MODELO, "").strip()
        if not url or not modelo:
            return None
        return ProveedorOpenAI(url, modelo, entorno.get(VAR_CLAVE, "").strip() or None)

    @property
    def descripcion(self) -> str:
        clave = "con clave" if self._clave else "sin clave"
        # La clave NUNCA se imprime, solo si existe o no.
        return f"{self._url} · modelo {self._modelo} · {clave}"

    def consultar(self, instruccion: str, texto: str) -> str:
        """Hace una petición «chat/completions» y devuelve el texto generado."""
        cuerpo = json.dumps(
            {
                "model": self._modelo,
                "messages": [
                    {"role": "system", "content": instruccion},
                    {"role": "user", "content": texto},
                ],
                "temperature": 0.2,  # poco creativo: queremos resúmenes fieles
            }
        ).encode("utf-8")
        cabeceras = {"Content-Type": "application/json"}
        if self._clave:
            cabeceras["Authorization"] = f"Bearer {self._clave}"
        peticion = urllib.request.Request(
            f"{self._url}/chat/completions", data=cuerpo, headers=cabeceras, method="POST"
        )

        try:
            with urllib.request.urlopen(peticion, timeout=self._tiempo_max) as respuesta:  # noqa: S310
                datos = json.loads(respuesta.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            # El servidor SÍ contestó, pero con un error HTTP. (Este except va
            # antes que URLError porque HTTPError es una subclase suya.)
            raise self._error_http(error.code) from None
        except urllib.error.URLError as error:
            # No se pudo ni conectar: sin red, DNS roto, servidor apagado...
            raise SinRedError(
                f"No puedo conectar con el servidor de IA ({self._url}): {error.reason}",
                pista="Revisa tu conexión y que el servidor esté encendido. "
                "Las acciones que no usan IA siguen funcionando.",
            ) from None
        except TimeoutError:
            raise SinRedError(
                f"El servidor de IA ({self._url}) tardó demasiado en responder.",
                pista="Prueba de nuevo o con un fichero más corto.",
            ) from None
        except OSError as error:  # p. ej. conexión reiniciada a mitad de respuesta
            raise SinRedError(f"Se cortó la conexión con el servidor de IA: {error}") from None
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise IAError("El servidor de IA devolvió algo que no es JSON válido.") from None

        try:
            contenido = datos["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise IAError("La respuesta de la IA no tiene el formato esperado.") from None
        if not isinstance(contenido, str) or not contenido.strip():
            raise IAError("La IA devolvió una respuesta vacía.")
        return contenido.strip()

    @staticmethod
    def _error_http(codigo: int) -> IAError:
        """Traduce un código HTTP a un mensaje humano (sin filtrar datos sensibles)."""
        if codigo in (401, 403):
            return IAError(
                f"El servidor de IA rechazó la clave (HTTP {codigo}).",
                pista=f"Revisa {VAR_CLAVE} en tu .env.",
            )
        if codigo == 404:
            return IAError(
                "El servidor de IA no encuentra esa ruta o ese modelo (HTTP 404).",
                pista=f"Revisa {VAR_URL} y {VAR_MODELO}.",
            )
        if codigo == 429:
            return IAError("Demasiadas peticiones al servidor de IA (HTTP 429). Espera un poco.")
        return IAError(f"El servidor de IA devolvió un error (HTTP {codigo}).")


def crear_proveedor() -> ProveedorIA | None:
    """Atajo para la CLI: proveedor según el entorno actual, o None si no hay IA."""
    return ProveedorOpenAI.desde_entorno()


def exigir_proveedor(ia: ProveedorIA | None) -> ProveedorIA:
    """Devuelve ``ia`` o lanza IANoDisponible con instrucciones de configuración."""
    if ia is None:
        raise IANoDisponible(
            "La IA no está configurada.",
            pista=f"Define {VAR_URL} y {VAR_MODELO} en tu .env (mira .env.example).",
        )
    return ia
