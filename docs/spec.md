# Especificación de `tareas` (10 líneas)

1. **Para quién:** cualquier persona que acumule ficheros desordenados (descargas, fotos, apuntes) y no quiera ordenarlos a mano.
2. **Problema:** tareas repetitivas con ficheros que se hacen mal y tarde: mover, renombrar, borrar temporales, quitar duplicados, resumir documentos.
3. **Idea:** una CLI instalable (`tareas`) cuyas acciones se describen en `acciones.json`, no en el código.
4. **Órdenes:** `version`, `listar [CARPETA]`, `acciones`, `validar`, `ejecutar NOMBRE [CARPETA]`, `ia`, y la opción global `--config`.
5. **Seguridad por defecto:** `--simular` enseña el plan sin tocar nada; borrar siempre pregunta (salvo `--si`); nunca se sobrescribe un fichero.
6. **Tipos de acción:** mover, copiar, borrar, renombrar, ordenar por tipo, duplicados, resumir con IA, renombrar por contenido con IA, y cadenas de varias acciones.
7. **IA opcional:** modelo compatible con la API de OpenAI (los del centro u Ollama); la clave va en `.env`. Sin IA o sin red, la herramienta lo explica y sigue con todo lo demás.
8. **Errores:** excepciones propias con mensajes para personas; códigos de salida 0 bien · 1 fallo · 2 uso · 3 configuración inválida; nunca un traceback.
9. **Plataformas:** Linux, Windows y macOS (pruebas en los tres con GitHub Actions); se instala con `uv tool install`.
10. **Fuera de alcance (NO hace):** no sincroniza con la nube, no tiene interfaz gráfica, no deshace operaciones ya aplicadas y no lee imágenes ni Office con la IA (solo PDF y texto).
