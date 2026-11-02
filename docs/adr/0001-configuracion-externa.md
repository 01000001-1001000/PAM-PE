# ADR 0001 · Las acciones viven en `acciones.json`, no en el código

- **Estado:** Aceptada
- **Fecha:** 2026-10-29
- **Contexto del proyecto:** CLI `tareas` (Proyecto 2 · Curso de Programación con IA)

## Contexto

`tareas` tiene que hacer trabajo útil sobre los ficheros de cada persona:
ordenar las descargas, renombrar fotos, limpiar temporales, resumir apuntes…
Lo que es «útil» cambia de una persona a otra (¿qué carpeta?, ¿qué extensiones?,
¿cuántos días de antigüedad?) y cambia con el tiempo: hoy quiero ordenar PDF,
mañana también `.epub`.

Hay que decidir **dónde se describe cada acción**: dentro del código Python o en
un fichero de datos que la persona edita.

## Decisión

Las acciones se describen en un fichero **`acciones.json`** que escribe la
persona usuaria. El código solo contiene el *motor* genérico que sabe
interpretar cualquier descripción válida:

```
acciones.json  ──►  config.py (valida)  ──►  Accion.desde_dict (fábrica)
                                                   │
                                  Motor ◄── Accion.planificar() ──► Plan
```

- Cada **tipo** de acción (`mover`, `renombrar`, `borrar`, `ia_resumir`…) es una
  clase; el campo `"tipo"` del JSON elige la clase (patrón *factory*).
- **Añadir una acción nueva = añadir un bloque JSON.** No se toca ni una línea
  de Python, no se reinstala la herramienta.
- **Añadir un tipo nuevo = añadir una clase** con su atributo `tipo`; se registra
  sola (`__init_subclass__`) y el motor no cambia.
- El fichero **no es de fiar** (lo escribe una persona): `config.py` lo valida
  entero y `tareas validar` dice el campo exacto que falla, con el código de
  salida 3.

## Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| **Acciones escritas en el código** (una función por acción) | Cada cambio de ruta o de extensión obliga a editar Python, volver a probar y reinstalar. La persona usuaria no tiene por qué saber programar. Mezcla *qué* se hace (datos) con *cómo* se hace (lógica). |
| **Argumentos en la línea de órdenes** (`tareas mover --ext .pdf --a ~/PDF`) | No se pueden guardar, versionar ni compartir; las órdenes largas se olvidan; no permite cadenas de acciones. |
| **YAML o TOML** en vez de JSON | Son más cómodos de escribir (comentarios), pero JSON viene en la biblioteca estándar (cero dependencias), lo lee cualquier otra herramienta (`jq`) y es el formato que ya conoce el alumnado. |
| **Una base de datos** (SQLite) | Excesivo para decenas de acciones; no se puede editar con un editor de texto ni revisar en un *diff* de git. |

## Consecuencias

**Positivas**

- Añadir o cambiar acciones **no exige tocar código**: se prueba con `tareas validar`
  y `tareas ejecutar … --simular` al instante.
- El fichero se versiona en git: el historial cuenta cómo evolucionan las acciones.
- La validación en un solo sitio permite mensajes de error muy claros (ruta exacta
  del campo, sugerencia ante erratas como `extensions` → `extensiones`).
- Se pueden tener varios ficheros (`--config trabajo.json`, `--config casa.json`).
- Las pruebas generan JSON temporales en vez de montar clases a mano.

**Negativas / costes asumidos**

- Hay que **escribir un validador** (`config.py`, `validacion.py`). Sin él, una
  errata se ignoraría en silencio y una acción podría afectar a más ficheros de
  los previstos. Por eso se rechazan las claves desconocidas y un `borrar` sin
  filtro.
- JSON **no admite comentarios**; la documentación de cada campo vive en el README.
- Una persona puede escribir una acción *válida* pero peligrosa (p. ej. borrar
  `*.pdf`). Se mitiga con `--simular`, la confirmación obligatoria al borrar y la
  negativa a borrar en la raíz del disco o en la carpeta personal completa.
- El esquema tiene un campo `"version"` para poder cambiar el formato en el
  futuro sin romper los ficheros antiguos.
