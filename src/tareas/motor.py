"""El MOTOR: ejecuta acciones de principio a fin.

Responsabilidad: coordinar «planificar -> mostrar -> confirmar -> aplicar».
Lo que NO hace: imprimir, usar colores ni conocer Typer. Todo lo que tenga que
comunicar a la persona lo hace a través de un ``Observador`` (patrón
Observer): la CLI pasa uno que dibuja tablas; las pruebas pasan uno silencioso.
Gracias a eso el motor se puede probar y reutilizar sin una terminal.

"""

from __future__ import annotations

import errno
import shutil
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .acciones import Accion, AccionSimple, Cadena
from .errores import AccionNoValida, IAError, TareasError
from .ia import ProveedorIA
from .plan import Contexto, Informe, Operacion, Plan


class Observador(Protocol):
    """Lo que el motor necesita de «quien le escucha».

    ``Protocol`` = tipado estructural: cualquier clase con estos métodos vale,
    sin heredar de nada.
    """

    def plan(self, plan: Plan) -> None:
        """Se muestra el plan que se va a simular/aplicar."""

    def aviso(self, mensaje: str) -> None:
        """Un aviso no fatal (paso omitido, simulación aproximada...)."""

    def confirmar(self, plan: Plan) -> bool:
        """Pregunta si aplicar el plan. Devuelve False para cancelar."""

    def paso(self, nombre: str, numero: int, total: int) -> None:
        """Empieza el paso ``numero`` de ``total`` de una cadena."""


class ObservadorSilencioso:
    """Observador que no imprime nada: para pruebas y uso como librería."""

    def __init__(self, confirma: bool = True) -> None:
        self._confirma = confirma
        self.planes: list[Plan] = []
        self.avisos: list[str] = []
        self.preguntas = 0  # cuántas veces se pidió confirmación

    def plan(self, plan: Plan) -> None:
        self.planes.append(plan)

    def aviso(self, mensaje: str) -> None:
        self.avisos.append(mensaje)

    def confirmar(self, plan: Plan) -> bool:
        self.preguntas += 1
        return self._confirma

    def paso(self, nombre: str, numero: int, total: int) -> None:
        pass


class Motor:
    """Ejecuta acciones sobre carpetas."""

    def __init__(
        self,
        ia: ProveedorIA | None = None,
        reloj: Callable[[], datetime] = datetime.now,
    ) -> None:
        # Guion bajo = atributo privado por convención: se usa solo dentro de la clase.
        self._ia = ia
        self._reloj = reloj  # inyectable: en pruebas se pasa un reloj falso

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------
    def ejecutar(
        self,
        accion: Accion,
        carpeta: Path | None,
        *,
        simular: bool,
        observador: Observador,
    ) -> Informe:
        """Ejecuta (o simula) una acción.

        Args:
            accion:     la acción a ejecutar.
            carpeta:    carpeta indicada por la persona (None = usar el origen
                        de la acción o, si no tiene, la carpeta actual).
            simular:    si True, enseña el plan y NO toca nada.
            observador: a quién se comunica el plan, avisos y confirmaciones.
        Raises:
            AccionNoValida: la carpeta no existe o es demasiado peligrosa.
            IAError: la acción necesita IA y no está disponible (acción suelta).
        """
        if isinstance(accion, Cadena):
            return self._ejecutar_cadena(accion, carpeta, simular, observador)
        assert isinstance(accion, AccionSimple)  # solo hay estos dos tipos
        return self._ejecutar_simple(accion, carpeta, simular, observador)

    # ------------------------------------------------------------------
    # Acción simple: planificar -> mostrar -> (confirmar) -> aplicar
    # ------------------------------------------------------------------
    def _ejecutar_simple(
        self, accion: AccionSimple, carpeta: Path | None, simular: bool, observador: Observador
    ) -> Informe:
        carpeta_real = self._resolver_carpeta(accion, carpeta)
        contexto = Contexto(ia=self._ia, ahora=self._reloj())

        # 1) PLANIFICAR. Solo lee del disco. Si algo lanza una excepción aquí
        #    (p. ej. sin red al llamar a la IA) no se ha modificado nada.
        plan = accion.planificar(carpeta_real, contexto)

        # Aserción de desarrollo: nada de lo planificado debe salirse de lo
        # esperado (origen siempre dentro de la carpeta de trabajo).
        for operacion in plan.operaciones:
            assert operacion.origen is None or carpeta_real in operacion.origen.parents

        # 2) MOSTRAR el plan (siempre, también en ejecución real).
        observador.plan(plan)
        informe = Informe(accion.nombre, simulado=simular, previstas=len(plan.reales), avisos=list(plan.avisos))
        if not plan.reales:
            return informe  # nada que aplicar (puede haber operaciones «info»)

        # 3) SIMULAR: aquí termina. No se toca nada.
        if simular:
            return informe

        # 4) CONFIRMAR si la acción lo pide (borrados, por defecto).
        if accion.confirmar and not observador.confirmar(plan):
            informe.cancelado = True
            return informe

        # 5) APLICAR. Cada operación se intenta por separado: si una falla
        #    (permiso denegado, fichero abierto) se anota y se sigue con el resto.
        for operacion in plan.reales:
            try:
                self._aplicar(operacion)
                informe.aplicadas += 1
            except OSError as error:
                informe.fallos.append(self._explicar_fallo(operacion, error))
        return informe

    # ------------------------------------------------------------------
    # Cadena: cada paso se ejecuta completo antes del siguiente
    # ------------------------------------------------------------------
    def _ejecutar_cadena(
        self, cadena: Cadena, carpeta: Path | None, simular: bool, observador: Observador
    ) -> Informe:
        informe = Informe(cadena.nombre, simulado=simular)
        if simular:
            observador.aviso(
                "Simulación de una cadena: cada paso se calcula sobre el estado ACTUAL de las "
                "carpetas, sin los cambios de los pasos anteriores (que no se aplican)."
            )
        # Si la cadena tiene origen propio, se usa como carpeta por defecto de sus pasos.
        carpeta_cadena = carpeta if carpeta is not None else cadena.origen

        total = len(cadena.pasos_resueltos)
        for numero, paso in enumerate(cadena.pasos_resueltos, start=1):
            observador.paso(paso.nombre, numero, total)

            # MODO SIN IA: en una cadena, un paso con IA que no puede ejecutarse
            # se OMITE (se explica) y la cadena continúa con los demás.
            if paso.requiere_ia and self._ia is None:
                motivo = "IA no configurada (define TAREAS_IA_URL y TAREAS_IA_MODELO en .env)"
                observador.aviso(f"Paso '{paso.nombre}' omitido: {motivo}.")
                informe.pasos.append(Informe(paso.nombre, simulado=simular, omitido=motivo))
                continue

            try:
                hijo = self._ejecutar_simple(paso, carpeta_cadena, simular, observador)
            except IAError as error:
                # Sin red / clave inválida a mitad de cadena: se omite el paso
                # (no se aplicó nada, porque el fallo ocurre al planificar).
                observador.aviso(f"Paso '{paso.nombre}' omitido: {error.mensaje}")
                informe.pasos.append(Informe(paso.nombre, simulado=simular, omitido=error.mensaje))
                continue
            except TareasError as error:
                # Cualquier otro error (carpeta inexistente...) detiene la cadena:
                # los pasos siguientes dependen de que este haya ido bien.
                informe.pasos.append(Informe(paso.nombre, simulado=simular, fallos=[error.mensaje]))
                break

            informe.pasos.append(hijo)
            if hijo.cancelado:
                observador.aviso("Cadena detenida: has cancelado un paso.")
                break
        return informe

    # ------------------------------------------------------------------
    # Utilidades privadas
    # ------------------------------------------------------------------
    @staticmethod
    def _resolver_carpeta(accion: AccionSimple, carpeta: Path | None) -> Path:
        """Decide la carpeta de trabajo y comprueba que sea segura.

        Prioridad: la que escribe la persona > el ``origen`` de la acción >
        la carpeta actual. Es ``staticmethod`` porque no usa ``self``.
        """
        elegida = carpeta if carpeta is not None else accion.origen
        base = Path.cwd() if elegida is None else elegida
        # expanduser(): PowerShell no convierte «~»; así funciona en todas las shells.
        base = base.expanduser()
        if not base.is_dir():
            raise AccionNoValida(
                f"La carpeta '{base}' no existe o no es una carpeta.",
                pista="Revisa la ruta (o el campo 'origen' de la acción en acciones.json).",
            )
        base = base.resolve()  # ruta absoluta, sin '..' ni enlaces
        # Seguridad: una acción que puede borrar no se lanza sobre la raíz del
        # disco ni sobre toda la carpeta personal (un filtro mal escrito sería un desastre).
        if accion.es_destructiva and (base == Path(base.anchor) or base == Path.home().resolve()):
            raise AccionNoValida(
                f"Por seguridad, la acción '{accion.nombre}' (que puede borrar) no se ejecuta sobre '{base}'.",
                pista="Indica una subcarpeta concreta, p. ej. ~/Descargas.",
            )
        return base

    @staticmethod
    def _aplicar(operacion: Operacion) -> None:
        """Ejecuta UNA operación sobre el disco. Puede lanzar OSError."""
        tipo = operacion.tipo
        if tipo == "borrar":
            assert operacion.origen is not None
            operacion.origen.unlink()
            return

        assert operacion.destino is not None
        # Última barrera contra sobrescribir: entre planificar y aplicar ha podido
        # aparecer un fichero con ese nombre (otro programa, otro paso de la cadena).
        if operacion.destino.exists():
            raise FileExistsError(errno.EEXIST, "ya existe un fichero con ese nombre")
        operacion.destino.parent.mkdir(parents=True, exist_ok=True)

        if tipo == "mover":
            assert operacion.origen is not None
            shutil.move(str(operacion.origen), str(operacion.destino))
        elif tipo == "copiar":
            assert operacion.origen is not None
            shutil.copy2(operacion.origen, operacion.destino)  # copy2 conserva fechas
        elif tipo == "escribir":
            assert operacion.contenido is not None
            # newline="\n": mismo salto de línea en todos los sistemas.
            operacion.destino.write_text(operacion.contenido, encoding="utf-8", newline="\n")
        else:  # pragma: no cover - Operacion.__post_init__ ya lo impide
            raise AssertionError(f"operación no aplicable: {tipo}")

    @staticmethod
    def _explicar_fallo(operacion: Operacion, error: OSError) -> str:
        """Convierte un OSError técnico en una frase para personas."""
        nombre = (operacion.origen or operacion.destino or Path("?")).name
        if isinstance(error, PermissionError):
            motivo = "permiso denegado (¿el fichero está abierto en otro programa?)"
        elif isinstance(error, FileNotFoundError):
            motivo = "el fichero ya no existe"
        elif isinstance(error, FileExistsError):
            motivo = "ya existe un fichero con ese nombre (no se sobrescribe)"
        else:
            motivo = error.strerror or str(error)
        return f"{operacion.tipo} '{nombre}': {motivo}"


__all__ = ["Motor", "Observador", "ObservadorSilencioso"]
