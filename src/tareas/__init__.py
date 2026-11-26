"""tareas: una CLI para ordenar, renombrar y resumir tus ficheros.

Mapa del paquete (cada módulo tiene UNA responsabilidad):

    cli.py          Interfaz con la persona (Typer + Rich). No hace trabajo real.
    motor.py        Orquesta: planifica, pide confirmación y aplica. No sabe de Typer.
    acciones.py     Las clases Accion (mover, renombrar, borrar, IA...) y sus fábricas.
    filtros.py      Qué ficheros afecta una acción (extensión, patrón, antigüedad...).
    config.py       Lee y VALIDA acciones.json (desconfía de todo lo que lee).
    plan.py         Estructuras de datos: Operacion, Plan, Informe, Contexto.
    ia.py           Proveedor de IA (API compatible con OpenAI) y modo sin red.
    lector.py       Extrae texto de PDF y ficheros de texto para la IA.
    validacion.py   Pequeñas funciones para validar el JSON con mensajes claros.
    utilidades.py   Funciones sueltas: tamaños legibles, nombres seguros, hashes.
    errores.py      Excepciones propias, cada una con su código de salida.
"""

# ÚNICA fuente de verdad de la versión. pyproject.toml la lee desde aquí
# ([tool.hatch.version]) y `tareas version` la muestra.
__version__ = "1.0.0"
