"""Capa de IA: habla con un servidor de modelos y degrada con elegancia.

Diseño:

* ``ProveedorIA`` es una clase ABSTRACTA: define QUÉ se espera de un proveedor
  (``consultar``) sin decir cómo. Las acciones solo conocen esta interfaz, de
  modo que en las pruebas se sustituye por una IA falsa sin tocar la red.
* ``ProveedorOpenAI`` es la implementación real: cualquier servidor con la
  API «chat/completions» (los modelos del centro, Ollama, etc.). Usa solo la
  librería estándar (urllib), sin dependencias extra.
* Seguridad: la clave se lee de variables de entorno / .env, JAMÁS del código,
  y nunca se escribe en mensajes de error.
* MODO SIN RED: si no hay red o falta la configuración se lanza una excepción
  propia (``SinRedError`` / ``IANoDisponible``) y el motor explica la situación
  y sigue ofreciendo las acciones que no necesitan IA.
"""

