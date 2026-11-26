"""Pruebas de ia.py: el proveedor de IA y el «modo sin red».

No se usa internet NUNCA. Se levanta un servidor HTTP falso en ``127.0.0.1``
(en un hilo, en un puerto libre que elige el sistema) que imita la API
«chat/completions». Así se prueba el código REAL de red (urllib) de forma
rápida, determinista y gratis, y también en GitHub Actions.
"""

