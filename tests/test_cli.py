"""Pruebas de EXTREMO A EXTREMO de la interfaz (cli.py).

Se invoca la aplicación Typer como lo haría una persona (con ``CliRunner``) y se
comprueban las tres cosas que ve el usuario o un script:

    * el CÓDIGO DE SALIDA (0 bien · 1 fallo · 2 uso · 3 configuración),
    * lo que sale por pantalla,
    * que JAMÁS aparece un «Traceback» ante un error previsible.

Si Typer no está instalado (p. ej. un entorno mínimo) el fichero se salta
entero en lugar de fallar: ``importorskip`` lo gestiona.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("typer")
pytest.importorskip("rich")

from conftest import crear_fichero, escribir_config  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from tareas import __version__, cli  # noqa: E402
from tareas.cli import app  # noqa: E402

runner = CliRunner()


@pytest.fixture(autouse=True)
def consola_ancha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rich parte las líneas largas a 80 columnas cuando no hay terminal.
    Con 200 columnas los mensajes salen enteros y se pueden comprobar."""
    monkeypatch.setattr(cli.salida, "_width", 200, raising=False)
    monkeypatch.setattr(cli.errores, "_width", 200, raising=False)


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    """Un acciones.json de pruebas con una acción de cada clase relevante."""
    return escribir_config(
        tmp_path / "acciones.json",
        [
            {
                "nombre": "ordenar-pdf",
                "descripcion": "Mueve los PDF a PDF/",
                "tipo": "mover",
                "filtro": {"extensiones": [".pdf"]},
                "destino": "PDF",
            },
            {
                "nombre": "limpiar",
                "descripcion": "Borra los .tmp de más de 30 días",
                "tipo": "borrar",
                "filtro": {"patron": r".*\.tmp$", "mas_antiguo_que_dias": 30},
                "confirmar": True,
            },
            {"nombre": "resumir", "descripcion": "Resume con IA", "tipo": "ia_resumir"},
            {
                "nombre": "mantenimiento",
                "descripcion": "Ordena y resume",
                "tipo": "cadena",
                "pasos": ["ordenar-pdf", "resumir"],
            },
        ],
    )


def invocar(cfg: Path, *args: str, input: str | None = None):  # noqa: A002
    """Lanza `tareas --config <cfg> <args>` y devuelve el resultado."""
    return runner.invoke(app, ["--config", str(cfg), *args], input=input)


def sin_traceback(resultado) -> None:
    assert "Traceback" not in resultado.output


# ---------------------------------------------------------------- camino feliz
def test_version() -> None:
    resultado = runner.invoke(app, ["version"])

    assert resultado.exit_code == 0
    assert resultado.stdout.strip() == f"tareas {__version__}"


def test_help_lista_todas_las_ordenes() -> None:
    resultado = runner.invoke(app, ["--help"])

    assert resultado.exit_code == 0
    # La ayuda se genera sola a partir de las funciones: debe citar cada orden.
    for orden in ("version", "listar", "acciones", "validar", "ejecutar"):
        assert orden in resultado.stdout


def test_listar_en_json_conserva_tildes_y_espacios(tmp_path: Path) -> None:
    carpeta = tmp_path / "datos"
    crear_fichero(carpeta, "Apuntes de Física.pdf", "x" * 2048)

    resultado = runner.invoke(app, ["listar", str(carpeta), "--json"])

    assert resultado.exit_code == 0
    # stdout contiene SOLO el JSON (así se puede encadenar con `| jq`).
    filas = json.loads(resultado.stdout)
    assert filas[0]["nombre"] == "Apuntes de Física.pdf"
    assert filas[0]["bytes"] == 2048


def test_acciones_en_json_marca_las_que_usan_ia(cfg: Path) -> None:
    resultado = invocar(cfg, "acciones", "--json")

    assert resultado.exit_code == 0
    por_nombre = {a["nombre"]: a for a in json.loads(resultado.stdout)}
    assert por_nombre["resumir"]["requiere_ia"] is True
    assert por_nombre["ordenar-pdf"]["requiere_ia"] is False


def test_config_tambien_se_puede_dar_con_la_variable_de_entorno(cfg: Path) -> None:
    resultado = runner.invoke(app, ["acciones"], env={"TAREAS_CONFIG": str(cfg)})

    assert resultado.exit_code == 0
    assert "ordenar-pdf" in resultado.output


def test_validar_ok(cfg: Path) -> None:
    resultado = invocar(cfg, "validar")

    assert resultado.exit_code == 0
    assert "es válido" in resultado.output


def test_simular_no_toca_nada_y_sale_con_0(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "a.pdf")

    resultado = invocar(cfg, "ejecutar", "ordenar-pdf", str(carpeta), "--simular")

    assert resultado.exit_code == 0
    assert "SIMULACIÓN" in resultado.output
    # El fichero sigue donde estaba: --simular jamás modifica el disco.
    assert (carpeta / "a.pdf").exists() and not (carpeta / "PDF").exists()


def test_ejecutar_con_si_aplica_sin_preguntar(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "a.pdf")

    resultado = invocar(cfg, "ejecutar", "ordenar-pdf", str(carpeta), "--si")

    assert resultado.exit_code == 0
    assert (carpeta / "PDF" / "a.pdf").exists()


def test_json_de_ejecutar_es_un_informe_estable(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "a.pdf")

    resultado = invocar(cfg, "ejecutar", "ordenar-pdf", str(carpeta), "--simular", "--json")

    assert resultado.exit_code == 0
    informe = json.loads(resultado.stdout)  # si hubiera texto extra, esto fallaría
    assert informe["ok"] is True and informe["simulado"] is True and informe["previstas"] == 1


def test_borrar_pregunta_y_acepta_s(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    viejo = crear_fichero(carpeta, "viejo.tmp", dias=40)

    resultado = invocar(cfg, "ejecutar", "limpiar", str(carpeta), input="s\n")

    assert resultado.exit_code == 0
    assert not viejo.exists()


# ------------------------------------------------------------------ casos feos
def test_feo_cancelar_el_borrado_no_borra_y_sale_con_1(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    viejo = crear_fichero(carpeta, "viejo.tmp", dias=40)

    resultado = invocar(cfg, "ejecutar", "limpiar", str(carpeta), input="n\n")

    assert viejo.exists()  # lo importante: no se borró
    assert resultado.exit_code == 1
    assert "Cancelado" in resultado.output


def test_feo_sin_terminal_interactiva_no_borra_y_explica_que_usar(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    viejo = crear_fichero(carpeta, "viejo.tmp", dias=40)

    resultado = invocar(cfg, "ejecutar", "limpiar", str(carpeta), input="")  # entrada cerrada

    assert viejo.exists()
    assert "--si" in resultado.output  # le dice cómo confirmar en un script
    sin_traceback(resultado)


def test_feo_json_roto_sale_con_3_y_dice_la_linea(tmp_path: Path) -> None:
    roto = tmp_path / "roto.json"
    roto.write_text('{"version": 1,\n "acciones": [,]}', encoding="utf-8")

    resultado = invocar(roto, "validar")

    assert resultado.exit_code == 3
    assert "línea 2" in resultado.output
    sin_traceback(resultado)


def test_feo_errata_en_una_clave_sale_con_3_y_sugiere_la_correcta(tmp_path: Path) -> None:
    ruta = escribir_config(
        tmp_path / "errata.json",
        [{"nombre": "x", "descripcion": "d", "tipo": "mover", "destino": "d", "filtro": {"extensions": [".pdf"]}}],
    )

    resultado = invocar(ruta, "validar")

    assert resultado.exit_code == 3
    assert "extensiones" in resultado.output
    sin_traceback(resultado)


def test_feo_fichero_de_acciones_inexistente_sale_con_3(tmp_path: Path) -> None:
    resultado = invocar(tmp_path / "no-existe.json", "acciones")

    assert resultado.exit_code == 3
    assert "--config" in resultado.output  # explica cómo arreglarlo
    sin_traceback(resultado)


def test_feo_accion_inexistente_sale_con_2_y_lista_las_disponibles(cfg: Path) -> None:
    resultado = invocar(cfg, "ejecutar", "inventada")

    assert resultado.exit_code == 2
    assert "ordenar-pdf" in resultado.output
    sin_traceback(resultado)


def test_feo_carpeta_inexistente_sale_con_2(tmp_path: Path) -> None:
    resultado = runner.invoke(app, ["listar", str(tmp_path / "fantasma")])

    assert resultado.exit_code == 2
    assert "no existe" in resultado.output
    sin_traceback(resultado)


def test_feo_opcion_inexistente_la_gestiona_typer_con_codigo_2(cfg: Path) -> None:
    resultado = invocar(cfg, "ejecutar", "ordenar-pdf", "--volar")

    assert resultado.exit_code == 2
    sin_traceback(resultado)


def test_feo_accion_con_ia_sin_ia_configurada_explica_como_configurarla(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "apuntes.md", "texto")

    resultado = invocar(cfg, "ejecutar", "resumir", str(carpeta), "--si")

    assert resultado.exit_code == 1
    assert "IA no está configurada" in resultado.output
    assert "TAREAS_IA_URL" in resultado.output
    sin_traceback(resultado)


def test_feo_modo_sin_red_la_cadena_sigue_con_los_pasos_sin_ia(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "a.pdf")

    resultado = invocar(cfg, "ejecutar", "mantenimiento", str(carpeta), "--si")

    # El paso 1 (sin IA) se hizo; el paso 2 (IA) se OMITIÓ explicándolo, y no es un fallo.
    assert (carpeta / "PDF" / "a.pdf").exists()
    assert "Omitido" in resultado.output
    assert resultado.exit_code == 0
    sin_traceback(resultado)


def test_feo_json_no_interactivo_exige_si_o_simular_antes_de_borrar(cfg: Path, tmp_path: Path) -> None:
    carpeta = tmp_path / "pruebas"
    viejo = crear_fichero(carpeta, "viejo.tmp", dias=40)

    resultado = invocar(cfg, "ejecutar", "limpiar", str(carpeta), "--json")

    assert resultado.exit_code == 2
    assert viejo.exists()


def test_feo_un_bug_interno_no_enseña_traceback(cfg: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def explota(*args: object, **kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli.Motor, "ejecutar", explota)
    carpeta = tmp_path / "pruebas"
    crear_fichero(carpeta, "a.pdf")

    resultado = invocar(cfg, "ejecutar", "ordenar-pdf", str(carpeta), "--si")

    # Aunque sea un fallo que NO previmos, la persona ve una línea, no una pila de llamadas.
    assert resultado.exit_code == 1
    assert "Error inesperado" in resultado.output
    assert "TAREAS_DEBUG" in resultado.output
    sin_traceback(resultado)


def test_ia_sin_configurar_no_es_un_error(tmp_path: Path) -> None:
    resultado = runner.invoke(app, ["ia"])

    assert resultado.exit_code == 0
    assert "IA no configurada" in resultado.output


# ----------------------------------------------------- proceso real (python -m)
def test_python_m_tareas_arranca_como_un_proceso_real(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parent.parent / "src"
    entorno = {**os.environ, "PYTHONPATH": os.pathsep.join([str(src), os.environ.get("PYTHONPATH", "")])}

    proceso = subprocess.run(
        [sys.executable, "-m", "tareas", "version"],
        capture_output=True, text=True, encoding="utf-8", env=entorno, cwd=tmp_path, timeout=60,
    )

    assert proceso.returncode == 0
    assert proceso.stdout.strip() == f"tareas {__version__}"
