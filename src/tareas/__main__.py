"""Permite ejecutar la herramienta con ``python -m tareas``.

Es útil cuando el comando ``tareas`` aún no está en el PATH, y lo usan las
pruebas de extremo a extremo (arrancan un proceso real).
"""

from .cli import app

if __name__ == "__main__":
    # prog_name hace que --help muestre «tareas» en vez de «python -m tareas».
    app(prog_name="tareas")
