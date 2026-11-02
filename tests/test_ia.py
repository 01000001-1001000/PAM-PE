"""Pruebas de ia.py: el proveedor de IA y el «modo sin red».

No se usa internet NUNCA. Se levanta un servidor HTTP falso en ``127.0.0.1``
(en un hilo, en un puerto libre que elige el sistema) que imita la API
«chat/completions». Así se prueba el código REAL de red (urllib) de forma
rápida, determinista y gratis, y también en GitHub Actions.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from tareas.errores import IAError, IANoDisponible, SinRedError
from tareas.ia import (
    VAR_CLAVE,
    VAR_MODELO,
    VAR_URL,
    ProveedorOpenAI,
    crear_proveedor,
    exigir_proveedor,
)

CLAVE_SECRETA = "clave-falsa-de-prueba"


class ServidorFalso:
    """Servidor que responde lo que se le configure y guarda lo que recibe."""

    def __init__(self) -> None:
        self.estado = 200  # código HTTP de la respuesta
        self.cuerpo: bytes = json.dumps(
            {"choices": [{"message": {"content": "  respuesta de prueba  "}}]}
        ).encode()
        self.peticiones: list[dict[str, Any]] = []  # lo recibido, para comprobarlo
        servidor = self  # el manejador de abajo necesita acceder a esta instancia

        class Manejador(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - nombre fijado por http.server
                largo = int(self.headers.get("Content-Length", 0))
                servidor.peticiones.append(
                    {
                        "ruta": self.path,
                        "autorizacion": self.headers.get("Authorization"),
                        "cuerpo": json.loads(self.rfile.read(largo) or b"{}"),
                    }
                )
                self.send_response(servidor.estado)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(servidor.cuerpo)

            def log_message(self, *args: Any) -> None:  # silencia el log de cada petición
                pass

        # Puerto 0 = «que el sistema elija uno libre» (evita choques entre pruebas).
        self._http = HTTPServer(("127.0.0.1", 0), Manejador)
        self.url = f"http://127.0.0.1:{self._http.server_port}/v1"
        self._hilo = threading.Thread(target=self._http.serve_forever, daemon=True)

    def __enter__(self) -> ServidorFalso:
        self._hilo.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._http.shutdown()
        self._http.server_close()


@pytest.fixture(autouse=True)
def sin_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Que urllib no mande el tráfico de 127.0.0.1 a un proxy corporativo."""
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")


@pytest.fixture
def servidor() -> Iterator[ServidorFalso]:
    with ServidorFalso() as falso:
        yield falso


# ---------------------------------------------------------------- camino feliz
def test_consultar_envia_la_peticion_correcta_y_devuelve_el_texto(servidor: ServidorFalso) -> None:
    ia = ProveedorOpenAI(servidor.url, "modelo-x", CLAVE_SECRETA)

    respuesta = ia.consultar("Resume esto", "texto largo")

    # La respuesta se devuelve sin los espacios sobrantes.
    assert respuesta == "respuesta de prueba"
    peticion = servidor.peticiones[0]
    # Se llamó a la ruta estándar de la API y con la clave en la cabecera.
    assert peticion["ruta"] == "/v1/chat/completions"
    assert peticion["autorizacion"] == f"Bearer {CLAVE_SECRETA}"
    # El modelo y los mensajes (instrucción de sistema + texto de usuario) viajan en el cuerpo.
    assert peticion["cuerpo"]["model"] == "modelo-x"
    assert peticion["cuerpo"]["messages"] == [
        {"role": "system", "content": "Resume esto"},
        {"role": "user", "content": "texto largo"},
    ]


def test_sin_clave_no_se_envia_cabecera_de_autorizacion(servidor: ServidorFalso) -> None:
    ProveedorOpenAI(servidor.url, "m", None).consultar("i", "t")

    # Los servidores locales (Ollama) no usan clave: no se manda nada.
    assert servidor.peticiones[0]["autorizacion"] is None


def test_desde_entorno_crea_el_proveedor_y_nunca_muestra_la_clave() -> None:
    entorno = {VAR_URL: "http://localhost:11434/v1", VAR_MODELO: "llama3.2", VAR_CLAVE: CLAVE_SECRETA}

    ia = ProveedorOpenAI.desde_entorno(entorno)

    assert ia is not None
    # La descripción se imprime en pantalla (`tareas ia`): la clave JAMÁS puede aparecer.
    assert CLAVE_SECRETA not in ia.descripcion
    assert "con clave" in ia.descripcion


@pytest.mark.parametrize(
    "entorno",
    [{}, {VAR_URL: "http://x/v1"}, {VAR_MODELO: "m"}, {VAR_URL: "  ", VAR_MODELO: "m"}],
)
def test_si_falta_url_o_modelo_la_ia_no_esta_disponible(entorno: dict[str, str]) -> None:
    # Devuelve None (no lanza): «sin IA» es un estado normal, no un error.
    assert ProveedorOpenAI.desde_entorno(entorno) is None


def test_crear_proveedor_lee_las_variables_del_entorno_real(monkeypatch: pytest.MonkeyPatch) -> None:
    assert crear_proveedor() is None  # conftest borra las variables: arranca sin IA
    monkeypatch.setenv(VAR_URL, "http://localhost:1/v1")
    monkeypatch.setenv(VAR_MODELO, "m")
    assert crear_proveedor() is not None


def test_exigir_proveedor_explica_como_configurarlo() -> None:
    with pytest.raises(IANoDisponible) as error:
        exigir_proveedor(None)

    # El mensaje no es críptico: dice QUÉ variables definir y dónde.
    assert VAR_URL in (error.value.pista or "")
    assert VAR_MODELO in (error.value.pista or "")


# ------------------------------------------------------------------ casos feos
def test_feo_sin_red_lanza_sinrederror_con_pista() -> None:
    # Se reserva un puerto libre y se CIERRA: nadie escucha, la conexión es rechazada.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        puerto = sock.getsockname()[1]
    ia = ProveedorOpenAI(f"http://127.0.0.1:{puerto}/v1", "m", CLAVE_SECRETA, tiempo_max=3)

    with pytest.raises(SinRedError) as error:
        ia.consultar("i", "t")

    # El error ES una IAError (se captura junto a las demás) y orienta a la persona.
    assert isinstance(error.value, IAError)
    assert "acciones que no usan IA siguen funcionando" in (error.value.pista or "")
    # La clave nunca se cuela en un mensaje de error.
    assert CLAVE_SECRETA not in error.value.mensaje


@pytest.mark.parametrize(
    ("codigo", "fragmento"),
    [(401, "rechazó la clave"), (403, "rechazó la clave"), (404, "404"), (429, "Demasiadas"), (500, "HTTP 500")],
)
def test_feo_los_errores_http_se_traducen_a_mensajes_humanos(
    servidor: ServidorFalso, codigo: int, fragmento: str
) -> None:
    servidor.estado = codigo
    ia = ProveedorOpenAI(servidor.url, "m", CLAVE_SECRETA)

    with pytest.raises(IAError) as error:
        ia.consultar("i", "t")

    assert fragmento in error.value.mensaje
    # Un error HTTP NO es «sin red»: el servidor respondió. Y no filtra la clave.
    assert not isinstance(error.value, SinRedError)
    assert CLAVE_SECRETA not in error.value.mensaje


@pytest.mark.parametrize(
    "cuerpo",
    [b"esto no es json", b"{}", b'{"choices": []}', b'{"choices":[{"message":{"content":"   "}}]}'],
)
def test_feo_respuestas_ilegibles_o_vacias_son_iaerror(servidor: ServidorFalso, cuerpo: bytes) -> None:
    servidor.cuerpo = cuerpo

    with pytest.raises(IAError):
        ProveedorOpenAI(servidor.url, "m").consultar("i", "t")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://servidor/x", "localhost:11434"])
def test_feo_solo_se_aceptan_urls_http(url: str) -> None:
    # Seguridad: urllib sabe abrir file://, y un .env manipulado no debe poder leer ficheros.
    with pytest.raises(IAError):
        ProveedorOpenAI(url, "m")
