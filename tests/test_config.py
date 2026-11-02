"""Pruebas de config.py: lectura y VALIDACIÓN de acciones.json.

Estructura de cada prueba (patrón AAA):
    Arrange (preparar)  ->  Act (ejecutar)  ->  Assert (comprobar)
Cada ``assert`` lleva un comentario que explica QUÉ garantiza y POR QUÉ importa.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import escribir_config

from tareas import config
from tareas.acciones import Borrar, Cadena, IaResumir, Mover, Renombrar
from tareas.errores import AccionNoValida, ConfigError


# ----------------------------------------------------------------- camino feliz
def test_carga_el_acciones_json_de_ejemplo_del_proyecto() -> None:
    """El acciones.json que se entrega con el proyecto debe ser válido."""
    raiz = Path(__file__).resolve().parent.parent
    configuracion = config.cargar(raiz / "acciones.json")

    # Hay al menos 5 acciones propias (rúbrica: «Excelente» exige 5 o más).
    assert len(configuracion.acciones) >= 5
    # Las dos acciones con IA existen (rúbrica: al menos 2 acciones con IA).
    con_ia = [a for a in configuracion.acciones.values() if a.requiere_ia]
    assert len(con_ia) >= 2
    # La cadena quedó enlazada con objetos reales, no con simples nombres.
    cadena = configuracion.acciones["mantenimiento-semanal"]
    assert isinstance(cadena, Cadena)
    assert len(cadena.pasos_resueltos) == len(cadena.pasos)


def test_la_fabrica_crea_la_clase_correcta_segun_el_tipo(tmp_path: Path) -> None:
    ruta = escribir_config(
        tmp_path / "a.json",
        [
            {"nombre": "mueve", "descripcion": "d", "tipo": "mover", "destino": "x"},
            {"nombre": "borra", "descripcion": "d", "tipo": "borrar", "filtro": {"extensiones": ["tmp"]}},
            {"nombre": "renombra", "descripcion": "d", "tipo": "renombrar", "plantilla": "{n:03}{ext}"},
            {"nombre": "resume", "descripcion": "d", "tipo": "ia_resumir"},
        ],
    )
    acciones = config.cargar(ruta).acciones

    # El campo «tipo» del JSON decide la clase concreta (patrón fábrica).
    assert isinstance(acciones["mueve"], Mover)
    assert isinstance(acciones["borra"], Borrar)
    assert isinstance(acciones["renombra"], Renombrar)
    assert isinstance(acciones["resume"], IaResumir)
    # "tmp" sin punto se normaliza a ".tmp": el usuario no tiene que acordarse del punto.
    assert acciones["borra"].filtro.extensiones == (".tmp",)
    # Borrar pide confirmación por defecto: seguridad ante todo.
    assert acciones["borra"].confirmar is True


def test_acepta_json_con_bom_de_windows(tmp_path: Path) -> None:
    """El Bloc de notas de Windows guarda UTF-8 con BOM; debe leerse igual."""
    ruta = tmp_path / "bom.json"
    ruta.write_bytes(
        b"\xef\xbb\xbf" + '{"version":1,"acciones":[{"nombre":"a","descripcion":"d","tipo":"mover","destino":"x"}]}'.encode()
    )
    # Si no se manejara el BOM, esto lanzaría ConfigError.
    assert "a" in config.cargar(ruta).acciones


# ------------------------------------------------------- CASOS FEOS (errores)
def test_feo_1_json_mal_escrito_dice_linea_y_columna(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.json"
    ruta.write_text('{\n  "version": 1,\n  "acciones": [ {"nombre": }\n}', encoding="utf-8")

    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)

    # Es un ConfigError (código 3), no un JSONDecodeError con traceback.
    assert error.value.codigo_salida == 3
    # El mensaje localiza el fallo: la persona sabe dónde mirar.
    assert "línea 3" in error.value.mensaje


def test_feo_2_fichero_inexistente_explica_como_solucionarlo(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as error:
        config.cargar(tmp_path / "no-existe.json")

    assert "No encuentro" in error.value.mensaje
    # La pista dice qué hacer (usar --config), no solo qué falló.
    assert error.value.pista is not None and "--config" in error.value.pista


def test_feo_3_reporta_todos_los_problemas_con_su_ruta(tmp_path: Path) -> None:
    ruta = escribir_config(
        tmp_path / "mal.json",
        [
            {"nombre": "Mal Nombre", "descripcion": "d", "tipo": "mover", "destino": "x"},
            {"nombre": "tipo-raro", "descripcion": "d", "tipo": "teletransportar"},
            {"nombre": "sin-destino", "descripcion": "d", "tipo": "mover"},
            {
                "nombre": "regex-rota",
                "descripcion": "d",
                "tipo": "mover",
                "destino": "x",
                "filtro": {"patron": "(sin cerrar"},
            },
        ],
    )
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)

    problemas = "\n".join(error.value.problemas)
    # Se acumulan los 4 fallos: se arreglan de una vez, no uno por intento.
    assert len(error.value.problemas) == 4
    assert "acciones[0] ('Mal Nombre').nombre" in problemas  # nombre con mayúsculas/espacio
    assert "'teletransportar' no existe" in problemas  # tipo inventado
    assert "necesitan la clave 'destino'" in problemas  # falta campo obligatorio
    assert "expresión regular inválida" in problemas  # regex rota


def test_clave_con_errata_sugiere_la_correcta(tmp_path: Path) -> None:
    """«extensions» en vez de «extensiones» se ignoraría y la acción afectaría a
    TODO. Por eso se rechaza y se sugiere la clave correcta."""
    ruta = escribir_config(
        tmp_path / "e.json",
        [{"nombre": "a", "descripcion": "d", "tipo": "mover", "destino": "x", "filtro": {"extensions": [".pdf"]}}],
    )
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)
    assert "¿Quisiste decir 'extensiones'?" in error.value.problemas[0]


@pytest.mark.parametrize(
    "plantilla, texto_esperado",
    [
        ("{fecha.year}", "no existe"),  # acceso a atributos: rechazado
        ("{inventado}", "no existe"),  # campo desconocido
        ("{n", "llaves mal cerradas"),  # llave sin cerrar
        ("{n:zz}", "formato inválido"),  # formato de número inválido
        ("a/{n}", "no puede"),  # separador de ruta: escaparía de la carpeta
    ],
)
def test_plantillas_peligrosas_o_rotas_se_rechazan_al_cargar(
    tmp_path: Path, plantilla: str, texto_esperado: str
) -> None:
    ruta = escribir_config(
        tmp_path / "p.json",
        [{"nombre": "a", "descripcion": "d", "tipo": "renombrar", "plantilla": plantilla}],
    )
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)
    # Falla al CARGAR (validar), no a mitad de renombrar 300 ficheros.
    assert texto_esperado in error.value.problemas[0]


def test_borrar_sin_filtro_se_rechaza(tmp_path: Path) -> None:
    """Un borrar sin filtro eliminaría TODOS los ficheros de la carpeta."""
    ruta = escribir_config(tmp_path / "b.json", [{"nombre": "a", "descripcion": "d", "tipo": "borrar"}])
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)
    assert "al menos una condición" in error.value.problemas[0]


def test_cadena_con_paso_inexistente_o_anidada(tmp_path: Path) -> None:
    ruta = escribir_config(
        tmp_path / "c.json",
        [
            {"nombre": "uno", "descripcion": "d", "tipo": "mover", "destino": "x"},
            {"nombre": "c1", "descripcion": "d", "tipo": "cadena", "pasos": ["uno", "fantasma"]},
            {"nombre": "c2", "descripcion": "d", "tipo": "cadena", "pasos": ["c1"]},
        ],
    )
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)
    texto = "\n".join(error.value.problemas)
    assert "'fantasma' no existe" in texto  # paso que no existe
    assert "no se permiten cadenas anidadas" in texto  # una cadena dentro de otra


def test_nombres_repetidos_y_version_incorrecta(tmp_path: Path) -> None:
    accion = {"nombre": "a", "descripcion": "d", "tipo": "mover", "destino": "x"}
    ruta = escribir_config(tmp_path / "r.json", [accion, accion], version=2)
    with pytest.raises(ConfigError) as error:
        config.cargar(ruta)
    texto = "\n".join(error.value.problemas)
    assert "repetido" in texto
    assert "version" in texto


def test_obtener_accion_inexistente_es_error_de_uso_codigo_2(tmp_path: Path) -> None:
    ruta = escribir_config(tmp_path / "o.json", [{"nombre": "a", "descripcion": "d", "tipo": "mover", "destino": "x"}])
    configuracion = config.cargar(ruta)

    with pytest.raises(AccionNoValida) as error:
        configuracion.obtener("nada")

    # Código 2 = error de uso (distinto del 3 de configuración inválida).
    assert error.value.codigo_salida == 2
    # La pista lista las acciones que SÍ existen.
    assert error.value.pista is not None and "a" in error.value.pista
