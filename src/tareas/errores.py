"""Excepciones propias de la herramienta.

Idea clave: cada error PREVISIBLE (carpeta que no existe, JSON mal escrito,
sin red...) es una excepción nuestra con un mensaje pensado para personas y
un CÓDIGO DE SALIDA. La capa de interfaz (cli.py) las captura todas en un
único sitio y las convierte en una línea de error limpia: nunca un traceback.

Códigos de salida (los de la especificación del proyecto):

    0  todo bien
    1  fallo al ejecutar (disco, permisos, IA caída, cancelado por el usuario)
    2  error de uso (acción inexistente, carpeta inexistente...)
    3  configuración inválida (acciones.json mal escrito)

Los scripts y la integración continua deciden con este número (`echo $?`).
"""

from __future__ import annotations

from collections.abc import Sequence


class TareasError(Exception):
    """Base de todos los errores previsibles de la herramienta.

    Atributos:
        mensaje: texto para la persona (qué ha pasado).
        pista:   texto opcional con qué hacer para arreglarlo.
        codigo_salida: número con el que termina el programa.
    """

    # Atributo de CLASE: cada subclase lo redefine. Por defecto, «fallo al ejecutar».
    codigo_salida: int = 1

    def __init__(self, mensaje: str, *, pista: str | None = None) -> None:
        # Se pasa el mensaje a Exception para que str(error) lo devuelva.
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.pista = pista


class ConfigError(TareasError):
    """acciones.json (o su ubicación) no es válido. Código de salida 3.

    ``problemas`` guarda la lista completa de fallos encontrados, para que la
    persona los arregle todos de una vez en lugar de uno por intento.
    """

    codigo_salida = 3

    def __init__(
        self,
        mensaje: str,
        *,
        problemas: Sequence[str] = (),
        pista: str | None = None,
    ) -> None:
        super().__init__(mensaje, pista=pista)
        # tuple: inmutable, para que nadie modifique la lista por accidente.
        self.problemas = tuple(problemas)


class AccionNoValida(TareasError):
    """Se ha pedido algo imposible: acción que no existe, carpeta inexistente,
    carpeta demasiado peligrosa para borrar... Es un error de USO (código 2).
    """

    codigo_salida = 2


class EjecucionError(TareasError):
    """Algo falló al tocar el sistema (permisos, fichero ocupado, PDF ilegible).
    Código de salida 1.
    """

    codigo_salida = 1


class IAError(TareasError):
    """La IA respondió mal o rechazó la petición (clave inválida, modelo
    inexistente...). Código de salida 1.
    """

    codigo_salida = 1


class IANoDisponible(IAError):
    """La IA no está configurada (faltan URL o modelo en el entorno/.env)."""


class SinRedError(IAError):
    """No hay conexión con el servidor de IA (sin red, servidor apagado, tiempo
    agotado). Es el aviso que activa el «modo sin red»: las acciones que no
    necesitan IA siguen funcionando.
    """
