# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y
versionado [SemVer](https://semver.org/lang/es/).

## [1.0.0] - 02-11-2026

Primera versión estable.

### Añadido
- Órdenes `version`, `listar`, `acciones`, `validar`, `ejecutar` e `ia`, con
  `--help` generado por Typer y la opción global `--config` (o `TAREAS_CONFIG`).
- Acciones definidas en `acciones.json`, validadas al cargar con mensajes que
  indican la ruta exacta del campo (`acciones[2] ('x').filtro.extensiones`).
- Tipos de acción: `mover`, `copiar`, `borrar`, `renombrar` (con plantilla),
  `ordenar_por_tipo`, `duplicados` (por contenido, SHA-256), `ia_resumir`,
  `ia_renombrar` y `cadena` (varias acciones con una sola orden).
- Filtros: `extensiones`, `patron` (expresión regular), `mas_antiguo_que_dias`
  y `mayor_que_mb`.
- Seguridad: `--simular`, confirmación `[s/N]` antes de borrar, `--si` para
  scripts, nunca se sobrescribe un fichero, se ignoran ocultos y enlaces
  simbólicos, y una acción que borra se niega a ejecutarse en la raíz del
  disco o en toda la carpeta personal.
- Capa de IA para servidores compatibles con la API de OpenAI (los modelos del
  centro, Ollama…); configuración por variables de entorno / `.env`.
- **Modo sin red:** sin IA configurada o sin conexión, la herramienta lo explica
  en una línea y las acciones sin IA siguen funcionando (en una cadena, el paso
  con IA se omite y continúa).
- Salida `--json` estable en `listar`, `acciones` y `ejecutar`.
- Excepciones propias (`ConfigError`, `AccionNoValida`, `EjecucionError`,
  `IAError`, `SinRedError`…) con código de salida: 0, 1, 2 y 3.
- Pruebas con pytest (camino feliz + casos feos) y CI en GitHub Actions sobre
  Linux, Windows y macOS.
- Documentación: README, especificación y ADR 0001 (configuración externa).
