"""Pruebas del MOTOR y las ACCIONES sobre ficheros reales en una carpeta temporal.

Camino feliz de cada acción + los casos feos que más duelen (no sobrescribir,
simular sin tocar, nombres con tildes y espacios, permisos, etc.).
"""

from __future__ import annotations

import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from conftest import IAFalsa, IASinRed, crear_fichero, escribir_config

from tareas import config
from tareas.errores import AccionNoValida, IANoDisponible, SinRedError
from tareas.motor import Motor, ObservadorSilencioso
from tareas.utilidades import nombre_libre, sanear_nombre, tamano_humano


def preparar(tmp_path: Path, *acciones: dict) -> "config.Configuracion":
    """Atajo: escribe un acciones.json con las acciones dadas y lo carga."""
    return config.cargar(escribir_config(tmp_path / "acciones.json", list(acciones)))


def accion(nombre: str, tipo: str, **extra) -> dict:
    return {"nombre": nombre, "descripcion": "prueba", "tipo": tipo, **extra}


# ======================================================================
# Acciones con ficheros (sin IA)
# ======================================================================
def test_mover_filtra_por_extension_y_mueve(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.pdf")
    crear_fichero(carpeta, "b.DOCX")  # mayúsculas: el filtro no distingue
    crear_fichero(carpeta, "c.png")
    cfg = preparar(tmp_path, accion("m", "mover", destino="docs", filtro={"extensiones": [".pdf", ".docx"]}))

    informe = Motor().ejecutar(cfg.obtener("m"), carpeta, simular=False, observador=ObservadorSilencioso())

    # 2 operaciones aplicadas de 2 previstas, sin fallos.
    assert (informe.previstas, informe.aplicadas, informe.fallos) == (2, 2, [])
    # Los ficheros del filtro están en su destino...
    assert (carpeta / "docs" / "a.pdf").exists() and (carpeta / "docs" / "b.DOCX").exists()
    # ...ya no están en el origen...
    assert not (carpeta / "a.pdf").exists()
    # ...y el que no cumplía el filtro no se ha tocado.
    assert (carpeta / "c.png").exists()


def test_simular_no_modifica_absolutamente_nada(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.pdf")
    crear_fichero(carpeta, "viejo.tmp", dias=90)
    cfg = preparar(
        tmp_path,
        accion("m", "mover", destino="docs"),
        accion("b", "borrar", filtro={"extensiones": [".tmp"]}),
    )
    antes = sorted(p.name for p in carpeta.rglob("*"))
    obs = ObservadorSilencioso()

    for nombre in ("m", "b"):
        informe = Motor().ejecutar(cfg.obtener(nombre), carpeta, simular=True, observador=obs)
        # La simulación informa de lo previsto pero NO aplica nada.
        assert informe.simulado and informe.aplicadas == 0 and informe.previstas > 0

    # El contenido de la carpeta es idéntico: nada creado, movido ni borrado.
    assert sorted(p.name for p in carpeta.rglob("*")) == antes
    # En simulación nunca se pregunta (no hay nada que confirmar).
    assert obs.preguntas == 0


def test_no_sobrescribe_nunca_si_el_destino_ya_existe(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.pdf", "NUEVO")
    crear_fichero(carpeta / "docs", "a.pdf", "ORIGINAL")
    cfg = preparar(tmp_path, accion("m", "mover", destino="docs", filtro={"extensiones": [".pdf"]}))

    Motor().ejecutar(cfg.obtener("m"), carpeta, simular=False, observador=ObservadorSilencioso())

    # El fichero que ya estaba conserva su contenido: no se pierde nada...
    assert (carpeta / "docs" / "a.pdf").read_text(encoding="utf-8") == "ORIGINAL"
    # ...y el que llega se guarda con otro nombre (a_1.pdf).
    assert (carpeta / "docs" / "a_1.pdf").read_text(encoding="utf-8") == "NUEVO"


def test_dos_ficheros_con_igual_nombre_destino_no_colisionan_ni_al_simular(tmp_path: Path, carpeta: Path) -> None:
    """Con recursivo, a/x.txt y b/x.txt van al mismo destino. Aunque en una
    simulación no se escriba nada, el plan ya debe darles nombres distintos."""
    crear_fichero(carpeta, "a/x.txt")
    crear_fichero(carpeta, "b/x.txt")
    cfg = preparar(tmp_path, accion("c", "copiar", destino="todo", recursivo=True, filtro={"extensiones": [".txt"]}))
    obs = ObservadorSilencioso()

    Motor().ejecutar(cfg.obtener("c"), carpeta, simular=True, observador=obs)

    destinos = [op.destino for op in obs.planes[0].operaciones]
    # Dos destinos, ambos distintos: se reservan los nombres durante la planificación.
    assert len(set(destinos)) == 2


def test_renombrar_con_plantilla_y_es_idempotente(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "IMG uno.JPG", dias=3)
    crear_fichero(carpeta, "IMG dos.jpg", dias=2)
    cfg = preparar(
        tmp_path,
        accion("r", "renombrar", filtro={"extensiones": [".jpg"]}, plantilla="foto_{n:03}{ext}"),
    )
    motor = Motor()

    informe = motor.ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())

    # Se numera por antigüedad: la más vieja es la 001. La extensión se conserva tal cual.
    assert informe.aplicadas == 2
    assert (carpeta / "foto_001.JPG").exists() and (carpeta / "foto_002.jpg").exists()
    # Segunda ejecución: ya tienen el nombre esperado, no hay nada que hacer
    # (idempotencia: ejecutar dos veces no rompe ni duplica).
    segunda = motor.ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())
    assert segunda.previstas == 0


def test_renombrar_usa_la_fecha_del_fichero(tmp_path: Path, carpeta: Path) -> None:
    fichero = crear_fichero(carpeta, "foto.jpg")
    instante = datetime(2026, 10, 26, 12, 0).timestamp()
    os.utime(fichero, (instante, instante))
    cfg = preparar(tmp_path, accion("r", "renombrar", plantilla="{fecha:%Y-%m-%d}_{n:03}{ext}"))

    Motor().ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())

    # El ejemplo literal de la web del curso: 2026-10-26_001.jpg
    assert (carpeta / "2026-10-26_001.jpg").exists()


def test_nombres_con_tildes_espacios_y_corchetes(tmp_path: Path, carpeta: Path) -> None:
    """Caso feo clásico: «Apuntes de Física [v2].pdf» no debe romper nada."""
    crear_fichero(carpeta, "Apuntes de Física [v2].pdf")
    cfg = preparar(tmp_path, accion("m", "mover", destino="Documentos PDF", filtro={"extensiones": [".pdf"]}))

    informe = Motor().ejecutar(cfg.obtener("m"), carpeta, simular=False, observador=ObservadorSilencioso())

    assert informe.aplicadas == 1
    assert (carpeta / "Documentos PDF" / "Apuntes de Física [v2].pdf").exists()


def test_borrar_solo_los_antiguos_y_pide_confirmacion(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "viejo.tmp", dias=45)
    crear_fichero(carpeta, "nuevo.tmp", dias=2)
    crear_fichero(carpeta, "importante.pdf", dias=400)
    cfg = preparar(
        tmp_path,
        accion("b", "borrar", filtro={"patron": r".*\.tmp$", "mas_antiguo_que_dias": 30}),
    )
    obs = ObservadorSilencioso(confirma=True)

    informe = Motor().ejecutar(cfg.obtener("b"), carpeta, simular=False, observador=obs)

    # Se pidió confirmación exactamente una vez (borrar es destructiva).
    assert obs.preguntas == 1
    # Solo desapareció el .tmp antiguo: el reciente y el PDF (aunque sea viejo) siguen.
    assert not (carpeta / "viejo.tmp").exists()
    assert (carpeta / "nuevo.tmp").exists() and (carpeta / "importante.pdf").exists()
    assert informe.aplicadas == 1


def test_si_el_usuario_cancela_no_se_borra_nada(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "viejo.tmp", dias=45)
    cfg = preparar(tmp_path, accion("b", "borrar", filtro={"extensiones": [".tmp"]}))

    informe = Motor().ejecutar(
        cfg.obtener("b"), carpeta, simular=False, observador=ObservadorSilencioso(confirma=False)
    )

    # Cancelado: el fichero sigue ahí y el informe lo refleja (ok=False -> código de salida 1).
    assert informe.cancelado and not informe.ok
    assert (carpeta / "viejo.tmp").exists()


def test_borrar_se_niega_en_la_raiz_y_en_la_carpeta_personal(tmp_path: Path) -> None:
    cfg = preparar(tmp_path, accion("b", "borrar", filtro={"extensiones": [".tmp"]}))

    for peligrosa in (Path(Path.home().anchor), Path.home()):
        with pytest.raises(AccionNoValida) as error:
            Motor().ejecutar(cfg.obtener("b"), peligrosa, simular=True, observador=ObservadorSilencioso())
        # Ni siquiera simulando: por seguridad, la acción destructiva se rechaza.
        assert "no se ejecuta sobre" in error.value.mensaje


def test_carpeta_inexistente_es_error_de_uso(tmp_path: Path) -> None:
    cfg = preparar(tmp_path, accion("m", "mover", destino="x"))
    with pytest.raises(AccionNoValida) as error:
        Motor().ejecutar(cfg.obtener("m"), tmp_path / "no-existe", simular=True, observador=ObservadorSilencioso())
    assert error.value.codigo_salida == 2
    assert "no existe" in error.value.mensaje


def test_ordenar_por_tipo_reparte_en_subcarpetas(tmp_path: Path, carpeta: Path) -> None:
    for nombre in ("a.pdf", "b.JPG", "c.zip", "d.desconocida"):
        crear_fichero(carpeta, nombre)
    cfg = preparar(tmp_path, accion("o", "ordenar_por_tipo"))
    obs = ObservadorSilencioso()

    Motor().ejecutar(cfg.obtener("o"), carpeta, simular=False, observador=obs)

    assert (carpeta / "PDF" / "a.pdf").exists()
    assert (carpeta / "Imagenes" / "b.JPG").exists()  # extensión en mayúsculas reconocida
    assert (carpeta / "Comprimidos" / "c.zip").exists()
    # Lo desconocido se queda donde está y se AVISA (no desaparece en silencio).
    assert (carpeta / "d.desconocida").exists()
    assert any("sin categoría" in aviso for aviso in obs.planes[0].avisos)


def test_ordenar_por_tipo_con_categorias_propias(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "nota.txt")
    cfg = preparar(tmp_path, accion("o", "ordenar_por_tipo", categorias={"Notas": ["txt"]}))
    Motor().ejecutar(cfg.obtener("o"), carpeta, simular=False, observador=ObservadorSilencioso())
    assert (carpeta / "Notas" / "nota.txt").exists()


def test_duplicados_detecta_por_contenido_no_por_nombre(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "original.txt", "mismo contenido", dias=10)  # el más antiguo se conserva
    crear_fichero(carpeta, "copia.txt", "mismo contenido", dias=1)
    crear_fichero(carpeta, "otro.txt", "contenido DISTINTO")
    crear_fichero(carpeta, "vacio1.txt", "")  # los vacíos se ignoran
    crear_fichero(carpeta, "vacio2.txt", "")
    cfg = preparar(tmp_path, accion("d", "duplicados", modo="mover", destino="Duplicados"))

    informe = Motor().ejecutar(cfg.obtener("d"), carpeta, simular=False, observador=ObservadorSilencioso())

    assert informe.aplicadas == 1
    # Se conserva el original (más antiguo) y se mueve la copia.
    assert (carpeta / "original.txt").exists()
    assert (carpeta / "Duplicados" / "copia.txt").exists()
    # Distinto contenido y ficheros vacíos: intactos.
    assert (carpeta / "otro.txt").exists() and (carpeta / "vacio1.txt").exists()


def test_duplicados_modo_informar_no_toca_nada(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt", "igual")
    crear_fichero(carpeta, "b.txt", "igual")
    cfg = preparar(tmp_path, accion("d", "duplicados"))  # modo por defecto: informar
    obs = ObservadorSilencioso()

    informe = Motor().ejecutar(cfg.obtener("d"), carpeta, simular=False, observador=obs)

    # Hay una operación «info» (visible en el plan) pero ninguna real.
    assert [op.tipo for op in obs.planes[0].operaciones] == ["info"]
    assert informe.previstas == 0 and (carpeta / "a.txt").exists() and (carpeta / "b.txt").exists()


def test_ignora_ficheros_ocultos_y_enlaces_simbolicos(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, ".env", "SECRETO=1")  # oculto: nunca se procesa
    cfg = preparar(tmp_path, accion("m", "mover", destino="x"))
    obs = ObservadorSilencioso()

    Motor().ejecutar(cfg.obtener("m"), carpeta, simular=False, observador=obs)

    # Un .env jamás se mueve por accidente.
    assert (carpeta / ".env").exists()
    assert obs.planes[0].operaciones == []


@pytest.mark.skipif(sys.platform == "win32", reason="los permisos POSIX no aplican igual en Windows")
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root ignora los permisos")
def test_fallo_de_permisos_se_anota_y_no_aborta_el_resto(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt")
    crear_fichero(carpeta, "b.txt")
    destino = carpeta / "bloqueado"
    destino.mkdir()
    cfg = preparar(tmp_path, accion("m", "mover", destino="bloqueado", filtro={"extensiones": [".txt"]}))
    destino.chmod(0o500)  # sin permiso de escritura
    try:
        informe = Motor().ejecutar(cfg.obtener("m"), carpeta, simular=False, observador=ObservadorSilencioso())
    finally:
        destino.chmod(0o700)  # restaurar para que pytest pueda limpiar

    # Los dos fallos se explican con palabras humanas y el informe NO es ok (código 1).
    assert len(informe.fallos) == 2 and not informe.ok
    assert "permiso denegado" in informe.fallos[0]


# ======================================================================
# Acciones con IA y modo sin red
# ======================================================================
def test_ia_resumir_escribe_el_resumen_junto_al_documento(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "apuntes.md", "Contenido del tema 1 sobre punteros.")
    cfg = preparar(tmp_path, accion("r", "ia_resumir", destino="Resumenes"))
    ia = IAFalsa("- Punteros: direcciones de memoria.")

    informe = Motor(ia=ia).ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())

    resumen = carpeta / "Resumenes" / "apuntes.md.resumen.md"
    assert informe.aplicadas == 1 and resumen.exists()
    texto = resumen.read_text(encoding="utf-8")
    # El resumen contiene lo que dijo la IA y avisa de que es generado por IA.
    assert "Punteros: direcciones de memoria" in texto and "Generado con IA" in texto
    # La IA recibió el TEXTO del documento (no la ruta ni otra cosa).
    assert "punteros" in ia.llamadas[0][1]


def test_ia_resumir_es_idempotente_y_no_resume_los_resumenes(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt", "hola")
    cfg = preparar(tmp_path, accion("r", "ia_resumir"))
    ia = IAFalsa()
    motor = Motor(ia=ia)

    motor.ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())
    llamadas_tras_la_primera = len(ia.llamadas)
    motor.ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())

    # La segunda vez no vuelve a gastar IA: ya existe el resumen (y el
    # propio .resumen.md no se vuelve a resumir).
    assert len(ia.llamadas) == llamadas_tras_la_primera == 1


def test_ia_renombrar_sanea_lo_que_devuelve_la_ia(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "scan0001.txt", "Informe de ventas del tercer trimestre")
    cfg = preparar(tmp_path, accion("n", "ia_renombrar"))
    # La IA desobedece: devuelve comillas, tildes, una ruta y una extensión.
    ia = IAFalsa('"../../Informe de Ventas Q3 (Año).txt"\nExplicación que sobra')

    Motor(ia=ia).ejecutar(cfg.obtener("n"), carpeta, simular=False, observador=ObservadorSilencioso())

    # Resultado seguro: sin «..», sin barras, sin tildes, extensión original conservada.
    # (Solo se mira la primera línea; la «explicación que sobra» se descarta.)
    assert [p.name for p in carpeta.iterdir()] == ["informe-de-ventas-q3-ano.txt"]


def test_sin_ia_configurada_una_accion_suelta_explica_como_configurarla(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt", "hola")
    cfg = preparar(tmp_path, accion("r", "ia_resumir"))

    with pytest.raises(IANoDisponible) as error:
        Motor(ia=None).ejecutar(cfg.obtener("r"), carpeta, simular=False, observador=ObservadorSilencioso())

    assert error.value.pista is not None and "TAREAS_IA_URL" in error.value.pista


def test_sin_red_no_se_aplica_nada_a_medias(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt", "hola")
    crear_fichero(carpeta, "b.txt", "adios")
    cfg = preparar(tmp_path, accion("n", "ia_renombrar"))

    with pytest.raises(SinRedError):
        Motor(ia=IASinRed()).ejecutar(cfg.obtener("n"), carpeta, simular=False, observador=ObservadorSilencioso())

    # El fallo ocurre al PLANIFICAR, antes de aplicar nada: los ficheros están intactos.
    assert sorted(p.name for p in carpeta.iterdir()) == ["a.txt", "b.txt"]


def test_cadena_sin_ia_omite_los_pasos_con_ia_y_sigue_con_el_resto(tmp_path: Path, carpeta: Path) -> None:
    """EL MODO SIN RED: la cadena explica qué omite y completa lo demás."""
    crear_fichero(carpeta, "a.pdf")
    crear_fichero(carpeta, "viejo.tmp", dias=60)
    cfg = preparar(
        tmp_path,
        accion("limpiar", "borrar", filtro={"extensiones": [".tmp"]}),
        accion("resumir", "ia_resumir"),
        accion("ordenar", "ordenar_por_tipo"),
        accion("todo", "cadena", pasos=["limpiar", "resumir", "ordenar"]),
    )
    obs = ObservadorSilencioso()

    informe = Motor(ia=None).ejecutar(cfg.obtener("todo"), carpeta, simular=False, observador=obs)

    # Los pasos sin IA se hicieron: el .tmp se borró y el PDF se ordenó.
    assert not (carpeta / "viejo.tmp").exists()
    assert (carpeta / "PDF" / "a.pdf").exists()
    # El paso con IA se omitió CON explicación (no con un traceback)...
    assert informe.pasos[1].omitido is not None and "IA no configurada" in informe.pasos[1].omitido
    assert any("omitido" in aviso for aviso in obs.avisos)
    # ...y omitir un paso NO cuenta como fallo: el informe global es correcto (código 0).
    assert informe.ok


def test_cadena_sin_red_a_mitad_tambien_se_degrada(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "a.txt", "hola")
    cfg = preparar(
        tmp_path,
        accion("resumir", "ia_resumir"),
        accion("ordenar", "ordenar_por_tipo"),
        accion("todo", "cadena", pasos=["resumir", "ordenar"]),
    )
    informe = Motor(ia=IASinRed()).ejecutar(
        cfg.obtener("todo"), carpeta, simular=False, observador=ObservadorSilencioso()
    )

    # La IA estaba «configurada» pero sin red: mismo comportamiento, se omite y se sigue.
    assert informe.pasos[0].omitido is not None
    assert (carpeta / "Documentos" / "a.txt").exists()
    assert informe.ok


def test_cadena_se_detiene_si_el_usuario_cancela_un_paso(tmp_path: Path, carpeta: Path) -> None:
    crear_fichero(carpeta, "viejo.tmp", dias=60)
    crear_fichero(carpeta, "a.pdf")
    cfg = preparar(
        tmp_path,
        accion("limpiar", "borrar", filtro={"extensiones": [".tmp"]}),
        accion("ordenar", "ordenar_por_tipo"),
        accion("todo", "cadena", pasos=["limpiar", "ordenar"]),
    )
    informe = Motor().ejecutar(
        cfg.obtener("todo"), carpeta, simular=False, observador=ObservadorSilencioso(confirma=False)
    )

    # Cancelar el borrado detiene la cadena: el paso 2 no llegó a ejecutarse.
    assert len(informe.pasos) == 1 and informe.pasos[0].cancelado
    assert (carpeta / "a.pdf").exists() and not (carpeta / "PDF").exists()


# ======================================================================
# Utilidades puras
# ======================================================================
@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("Informe de Ventas Q3", "informe-de-ventas-q3"),
        ("Física y Química: tema 2", "fisica-y-quimica-tema-2"),  # tildes fuera
        ("../../etc/passwd", "etc-passwd"),  # no puede escapar de la carpeta
        ("   ", ""),  # nada aprovechable
        ("con", "con-doc"),  # nombre reservado de Windows
    ],
)
def test_sanear_nombre(entrada: str, esperado: str) -> None:
    assert sanear_nombre(entrada) == esperado


def test_tamano_humano() -> None:
    assert tamano_humano(0) == "0 B"
    assert tamano_humano(1536) == "1.5 KB"
    assert tamano_humano(5 * 1024 * 1024) == "5.0 MB"


def test_nombre_libre_numera_hasta_encontrar_hueco(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "a_1.txt").write_text("x")
    reservados: set[str] = set()

    primero = nombre_libre(tmp_path / "a.txt", reservados)
    segundo = nombre_libre(tmp_path / "a.txt", reservados)

    # Salta a.txt y a_1.txt (existen) y, al pedir otro, no repite el reservado.
    assert primero.name == "a_2.txt" and segundo.name == "a_3.txt"


def test_hash_coincide_con_hashlib(tmp_path: Path) -> None:
    from tareas.utilidades import hash_fichero

    ruta = tmp_path / "f.bin"
    ruta.write_bytes(b"hola mundo" * 200_000)  # > 1 MB: obliga a leer por bloques
    assert hash_fichero(ruta) == hashlib.sha256(b"hola mundo" * 200_000).hexdigest()
