"""INTERFAZ de línea de órdenes (Typer + Rich).

Responsabilidad ÚNICA: hablar con la persona. Lee los argumentos, llama al
motor y dibuja el resultado. No contiene lógica de negocio.

Convenciones de salida (las de una CLI profesional):

* stdout  -> resultados (tablas, JSON). Se puede redirigir o encadenar con |.
* stderr  -> avisos y errores. Así `tareas listar --json | jq` nunca se mezcla
            con mensajes.
* códigos de salida -> 0 bien · 1 fallo al ejecutar · 2 error de uso · 3 config inválida.
* JAMÁS un traceback ante un error previsible.
"""

import functools
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Optional, TypeVar

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from . import __version__, config as modulo_config
from .errores import AccionNoValida, ConfigError, TareasError
from .ia import VAR_CLAVE, VAR_MODELO, VAR_URL, cargar_entorno, crear_proveedor
from .motor import Motor
from .plan import Informe, Plan
from .utilidades import tamano_humano

# -----------------------------------------------------------------------------
# La aplicación Typer. Typer lee las firmas de las funciones y los tipos para
# generar --help, validar argumentos y el autocompletado de la shell.
# -----------------------------------------------------------------------------
app = typer.Typer(
    name="tareas",
    help="Ordena, renombra y resume tus ficheros con acciones definidas en acciones.json.",
    no_args_is_help=True,  # `tareas` sin nada muestra la ayuda
    pretty_exceptions_enable=False,  # nada de tracebacks decorados de Rich
    context_settings={"help_option_names": ["-h", "--help"]},
)

# Dos consolas: una para resultados (stdout) y otra para mensajes (stderr).
salida = Console(highlight=False)
errores = Console(stderr=True, highlight=False)

# Límite de filas al mostrar un plan (si hay miles, se resume).
MAX_FILAS_PLAN = 100

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class Opciones:
    """Opciones globales (las de antes del subcomando) que comparten todos los comandos."""

    ruta_config: Path


# =============================================================================
# Gestión centralizada de errores
# =============================================================================
def _mostrar_error(error: TareasError) -> None:
    """Imprime un error previsible: una línea clara (+ lista de problemas + pista)."""
    errores.print(f"[bold red]Error:[/bold red] {escape(error.mensaje)}")
    if isinstance(error, ConfigError):
        for problema in error.problemas:
            errores.print(f"  - {escape(problema)}")
    if error.pista:
        errores.print(f"[dim]{escape(error.pista)}[/dim]")


def manejar_errores(funcion: F) -> F:
    """DECORADOR que envuelve cada comando para atrapar TODOS los errores en UN sitio.

    - TareasError (previsible)   -> mensaje limpio + su código de salida.
    - Ctrl+C                     -> salida 130 (convención de las shells).
    - Error inesperado (un bug)  -> mensaje corto; con TAREAS_DEBUG=1 se ve el
                                    traceback completo para depurar.
    """

    @functools.wraps(funcion)  # conserva nombre, docstring y firma (Typer los necesita)
    def envoltorio(*args: Any, **kwargs: Any) -> Any:
        try:
            return funcion(*args, **kwargs)
        except (typer.Exit, typer.Abort):
            raise  # son las señales normales de Typer: no tocar
        except TareasError as error:
            _mostrar_error(error)
            raise typer.Exit(error.codigo_salida) from None
        except KeyboardInterrupt:
            errores.print("[yellow]Interrumpido.[/yellow]")
            raise typer.Exit(130) from None
        except Exception as error:  # noqa: BLE001 - red de seguridad final
            # Las excepciones propias de Typer/Click (p. ej. un error de uso) las
            # gestiona el propio framework. NO se importa `click` aquí: las
            # versiones recientes de Typer traen el suyo interno y `click` puede
            # no estar instalado. Por eso se mira el paquete de origen de la clase.
            if type(error).__module__.split(".")[0] in ("typer", "click"):
                raise
            if os.environ.get("TAREAS_DEBUG"):
                raise
            errores.print(
                f"[bold red]Error inesperado:[/bold red] {escape(type(error).__name__)}: {escape(str(error))}"
            )
            errores.print("[dim]Ejecuta con TAREAS_DEBUG=1 para ver el detalle técnico.[/dim]")
            raise typer.Exit(1) from None

    return envoltorio  # type: ignore[return-value]


# =============================================================================
# Observador de consola: implementa el protocolo que pide el motor
# =============================================================================
class ObservadorConsola:
    """Dibuja el plan, los avisos y las preguntas en la terminal."""

    def __init__(self, *, json_salida: bool, simular: bool) -> None:
        self._json = json_salida
        self._simular = simular

    def plan(self, plan: Plan) -> None:
        if self._json:
            return  # en modo JSON solo se imprime el informe final
        for aviso in plan.avisos:
            errores.print(f"[yellow]Aviso:[/yellow] {escape(aviso)}")
        if not plan.operaciones:
            salida.print(f"[dim]'{escape(plan.accion)}': no hay nada que hacer en {escape(str(plan.carpeta))}.[/dim]")
            return
        titulo = f"{'SIMULACIÓN' if self._simular else 'Plan'}: {plan.accion}"
        tabla = Table(title=titulo, title_justify="left", show_lines=False)
        tabla.add_column("Operación")
        tabla.add_column("Fichero")
        tabla.add_column("Destino / nota")
        for operacion in plan.operaciones[:MAX_FILAS_PLAN]:
            # Text(...) en vez de un str: los nombres con corchetes [así] NO se
            # interpretan como marcas de formato de Rich.
            tabla.add_row(
                _etiqueta(operacion),
                Text(_corto(operacion.origen, plan.carpeta)),
                Text(_describir_destino(operacion, plan.carpeta)),
            )
        salida.print(tabla)
        if len(plan.operaciones) > MAX_FILAS_PLAN:
            salida.print(f"[dim]... y {len(plan.operaciones) - MAX_FILAS_PLAN} más[/dim]")

    def aviso(self, mensaje: str) -> None:
        if not self._json:
            errores.print(f"[yellow]Aviso:[/yellow] {escape(mensaje)}")

    def confirmar(self, plan: Plan) -> bool:
        """Pregunta «¿Aplicar...? [s/N]». Por defecto (Intro) la respuesta es NO.

        No se usa ``typer.confirm`` porque solo entiende «y/n» en inglés.
        ``err=True`` manda la pregunta a stderr: así, si rediriges stdout a un
        fichero o a ``jq``, la pregunta no se mezcla con los resultados.
        """
        pregunta = f"¿Aplicar {len(plan.reales)} operación(es) de '{plan.accion}'? [s/N]"
        try:
            respuesta = typer.prompt(
                pregunta, default="n", show_default=False, prompt_suffix=" ", err=True
            )
            # Se aceptan «s», «sí», «si», «y» y «yes» (con o sin mayúsculas/tilde).
            return respuesta.strip().lower() in {"s", "si", "sí", "y", "yes"}
        except typer.Abort:
            # Sin terminal interactiva (entrada vacía/cerrada) no se puede preguntar.
            errores.print("[dim]No hay terminal interactiva: usa --si para confirmar sin preguntar.[/dim]")
            return False

    def paso(self, nombre: str, numero: int, total: int) -> None:
        if not self._json:
            salida.print(f"[bold]Paso {numero}/{total}:[/bold] {escape(nombre)}")


def _corto(ruta: Path | None, base: Path) -> str:
    """Muestra la ruta relativa a la carpeta de trabajo, si se puede (más legible)."""
    if ruta is None:
        return ""
    try:
        return str(ruta.relative_to(base))
    except ValueError:
        return str(ruta)


def _etiqueta(operacion: Any) -> str:
    """Nombre de la operación para la 1.ª columna del plan.

    Internamente renombrar y mover son lo mismo (``mover``), pero a la persona
    le dice más «renombrar» cuando el fichero se queda en su misma carpeta.
    """
    if (
        operacion.tipo == "mover"
        and operacion.origen is not None
        and operacion.destino is not None
        and operacion.origen.parent == operacion.destino.parent
    ):
        return "renombrar"
    return operacion.tipo


def _describir_destino(operacion: Any, base: Path) -> str:
    """Texto de la 3.ª columna del plan: destino y/o nota."""
    partes = []
    if operacion.destino is not None and operacion.tipo != "escribir":
        partes.append(f"-> {_corto(operacion.destino, base)}")
    elif operacion.destino is not None:
        partes.append(f"crea {_corto(operacion.destino, base)}")
    if operacion.nota:
        partes.append(f"({operacion.nota})")
    return " ".join(partes)


# =============================================================================
# Callback global: se ejecuta ANTES de cualquier subcomando
# =============================================================================
@app.callback()
def principal(
    ctx: typer.Context,
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            envvar="TAREAS_CONFIG",  # también se puede fijar con la variable de entorno
            help="Fichero de acciones a usar.",
        ),
    ] = Path("acciones.json"),
) -> None:
    """Opciones que valen para todos los comandos."""
    _configurar_salida()
    cargar_entorno()  # lee el .env (claves de IA) a las variables de entorno
    ctx.obj = Opciones(ruta_config=config)


def _configurar_salida() -> None:
    """Fuerza UTF-8 en stdout/stderr (en Windows, redirigido, puede ser cp1252
    y las tildes y la ñ saldrían rotas)."""
    for flujo in (sys.stdout, sys.stderr):
        codificacion = (getattr(flujo, "encoding", None) or "").lower().replace("-", "")
        if codificacion != "utf8" and hasattr(flujo, "reconfigure"):
            try:
                flujo.reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # flujo ya cerrado o no reconfigurable
                pass


def _config_de(ctx: typer.Context) -> modulo_config.Configuracion:
    """Carga y valida acciones.json según la opción global --config."""
    opciones: Opciones = ctx.obj
    return modulo_config.cargar(opciones.ruta_config)


def _imprimir_json(datos: Any) -> None:
    """JSON estable y sin colores para otros programas. ensure_ascii=False
    conserva tildes y ñ legibles."""
    typer.echo(json.dumps(datos, ensure_ascii=False, indent=2))


# =============================================================================
# Comandos
# =============================================================================
@app.command()
@manejar_errores
def version() -> None:
    """Muestra la versión instalada."""
    typer.echo(f"tareas {__version__}")


@app.command()
@manejar_errores
def listar(
    carpeta: Annotated[
        Optional[Path],
        typer.Argument(help="Carpeta a listar (por defecto, la actual).", show_default=False),
    ] = None,
    json_salida: Annotated[
        bool, typer.Option("--json", help="Salida JSON, sin colores, para otros programas.")
    ] = False,
) -> None:
    """Lista los ficheros de una carpeta: nombre, tipo, tamaño y fecha."""
    base = (carpeta or Path.cwd()).expanduser()  # expanduser: ~ también en PowerShell
    if not base.is_dir():
        raise AccionNoValida(f"La carpeta '{base}' no existe o no es una carpeta.")

    filas: list[dict[str, Any]] = []
    try:
        entradas = sorted(base.iterdir(), key=lambda p: p.name.casefold())
    except OSError as error:
        raise AccionNoValida(f"No puedo leer '{base}': {error.strerror or error}") from None
    for entrada in entradas:
        try:
            estado = entrada.stat()
        except OSError:
            continue  # enlace roto o fichero que desaparece: se ignora
        es_carpeta = entrada.is_dir()
        filas.append(
            {
                "nombre": entrada.name,
                "tipo": "carpeta" if es_carpeta else (entrada.suffix.lower().lstrip(".") or "fichero"),
                "bytes": None if es_carpeta else estado.st_size,
                "modificado": datetime.fromtimestamp(estado.st_mtime).isoformat(timespec="seconds"),
            }
        )

    if json_salida:
        _imprimir_json(filas)
        return

    tabla = Table(title=str(base), title_justify="left")
    tabla.add_column("Nombre")
    tabla.add_column("Tipo")
    tabla.add_column("Tamaño", justify="right")
    tabla.add_column("Modificado")
    for fila in filas:
        tabla.add_row(
            Text(fila["nombre"]),
            fila["tipo"],
            "-" if fila["bytes"] is None else tamano_humano(fila["bytes"]),
            fila["modificado"].replace("T", " "),
        )
    salida.print(tabla)


@app.command()
@manejar_errores
def acciones(
    ctx: typer.Context,
    json_salida: Annotated[bool, typer.Option("--json", help="Salida JSON.")] = False,
) -> None:
    """Lista las acciones definidas en acciones.json."""
    configuracion = _config_de(ctx)
    hay_ia = crear_proveedor() is not None

    if json_salida:
        _imprimir_json(
            [
                {"nombre": a.nombre, "tipo": a.tipo, "descripcion": a.descripcion, "requiere_ia": a.requiere_ia}
                for a in configuracion.acciones.values()
            ]
        )
        return

    tabla = Table(title=f"Acciones de {configuracion.ruta.name}", title_justify="left")
    # no_wrap: el nombre es lo que se teclea en `tareas ejecutar NOMBRE`, así que
    # nunca debe cortarse con «…»; es la descripción la que se ajusta al ancho.
    tabla.add_column("Nombre", style="bold", no_wrap=True)
    tabla.add_column("Tipo")
    tabla.add_column("IA")
    tabla.add_column("Descripción")
    for accion in configuracion.acciones.values():
        if not accion.requiere_ia:
            marca = ""
        else:
            marca = "sí" if hay_ia else "sí (sin configurar)"
        tabla.add_row(accion.nombre, accion.tipo, marca, Text(accion.descripcion))
    salida.print(tabla)
    if not hay_ia:
        salida.print(f"[dim]IA no configurada: las acciones con IA se omiten. Mira .env.example.[/dim]")


@app.command()
@manejar_errores
def validar(ctx: typer.Context) -> None:
    """Comprueba acciones.json y dice exactamente qué campo falla (código 3 si es inválido)."""
    configuracion = _config_de(ctx)  # si hay problemas, lanza ConfigError -> código 3
    n = len(configuracion.acciones)
    salida.print(f"[green]OK[/green] {escape(configuracion.ruta.name)} es válido: {n} acción(es).")


@app.command()
@manejar_errores
def ejecutar(
    ctx: typer.Context,
    nombre: Annotated[str, typer.Argument(help="Acción a ejecutar (mira `tareas acciones`).")],
    carpeta: Annotated[
        Optional[Path],
        typer.Argument(
            help="Carpeta sobre la que trabajar (por defecto, el 'origen' de la acción o la carpeta actual).",
            show_default=False,
        ),
    ] = None,
    simular: Annotated[
        bool, typer.Option("--simular", help="Enseña qué haría, sin tocar nada.")
    ] = False,
    si: Annotated[
        bool, typer.Option("--si", help="Confirma sin preguntar (para scripts).")
    ] = False,
    json_salida: Annotated[
        bool, typer.Option("--json", help="Informe en JSON (requiere --simular o --si).")
    ] = False,
) -> None:
    """Ejecuta una acción de acciones.json."""
    configuracion = _config_de(ctx)
    accion = configuracion.obtener(nombre)  # AccionNoValida (código 2) si no existe

    # En modo JSON no se puede hacer una pregunta interactiva sin romper la salida.
    if json_salida and not simular and not si and accion.requiere_confirmacion:
        raise AccionNoValida(
            f"'{nombre}' pide confirmación y --json no es interactivo.",
            pista="Añade --simular para ver el plan o --si para confirmar de antemano.",
        )

    observador = ObservadorConsola(json_salida=json_salida, simular=simular)
    if si:
        # --si: el observador responde «sí» a todo sin preguntar.
        observador.confirmar = lambda plan: True  # type: ignore[method-assign]

    motor = Motor(ia=crear_proveedor())
    informe = motor.ejecutar(accion, carpeta, simular=simular, observador=observador)

    if json_salida:
        _imprimir_json(informe.a_dict())
    else:
        _resumen(informe)
    if not informe.ok:
        raise typer.Exit(1)


def _resumen(informe: Informe, sangria: str = "") -> None:
    """Imprime el resultado final de una ejecución (y de cada paso de una cadena)."""
    nombre = escape(informe.accion)
    if informe.omitido:
        salida.print(f"{sangria}[yellow]Omitido[/yellow] {nombre}: {escape(informe.omitido)}")
    elif informe.cancelado:
        salida.print(f"{sangria}[yellow]Cancelado[/yellow] {nombre}: no se ha modificado nada.")
    elif informe.pasos:
        for paso in informe.pasos:
            _resumen(paso, sangria + "  ")
    elif informe.simulado:
        salida.print(
            f"{sangria}[cyan]Simulación[/cyan] {nombre}: {informe.previstas} operación(es) previstas. "
            "No se ha modificado nada."
        )
    else:
        salida.print(f"{sangria}[green]Hecho[/green] {nombre}: {informe.aplicadas}/{informe.previstas} aplicadas.")
    for fallo in informe.fallos:
        errores.print(f"{sangria}[red]Fallo:[/red] {escape(fallo)}")


@app.command()
@manejar_errores
def ia(
    probar: Annotated[
        bool, typer.Option("--probar", help="Hace una petición real al servidor de IA.")
    ] = False,
) -> None:
    """Comprueba si la IA está configurada (y, con --probar, si responde)."""
    proveedor = crear_proveedor()
    if proveedor is None:
        salida.print("[yellow]IA no configurada.[/yellow]")
        salida.print(f"Define {VAR_URL} y {VAR_MODELO} (y {VAR_CLAVE} si hace falta) en tu .env.")
        salida.print("Mientras tanto, todas las acciones que no usan IA funcionan con normalidad.")
        return
    salida.print(f"IA configurada: {escape(proveedor.descripcion)}")
    if probar:
        respuesta = proveedor.consultar("Responde solo con la palabra: ok", "ping")  # SinRedError si falla
        salida.print(f"[green]El servidor responde:[/green] {escape(respuesta[:80])}")


if __name__ == "__main__":  # pragma: no cover
    app()
