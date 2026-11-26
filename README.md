# tareas · CLI para ordenar, renombrar y resumir tus ficheros

`tareas` es una herramienta de terminal (Python + Typer + uv) que trabaja con
**tus ficheros** mediante **acciones que defines tú en un `acciones.json`**:
ordenar descargas, renombrar fotos con su fecha, limpiar temporales, quitar
duplicados, resumir PDF con IA… Funciona en **Linux, Windows y macOS**.

- Las acciones **no están en el código**: añadir una es añadir un bloque JSON
  ([ADR 0001](docs/adr/0001-configuracion-externa.md)).
- **Seguridad por defecto:** `--simular` enseña qué haría sin tocar nada, borrar
  siempre pregunta y nunca se sobrescribe un fichero.
- **IA opcional:** sin IA o sin red lo explica en una línea y sigue con todo lo demás.

## Instalación (una sola orden)

Necesitas [uv](https://docs.astral.sh/uv/) (instala también Python 3.12 si falta).

```bash
# Linux / macOS: instalar uv (una vez)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

```powershell
# Windows (PowerShell): instalar uv (una vez)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Después, instala `tareas` **desde GitHub** (sustituye `TU-USUARIO`):

```bash
uv tool install git+https://github.com/01000001-1001000/PAM-PE
# o, si prefieres pipx:
pipx install git+https://github.com/01000001-1001000/PAM-PE
```

Comprueba que funciona **desde cualquier carpeta**:

```bash
tareas --help
tareas version
```

> Si tu terminal dice que no encuentra `tareas`, ejecuta `uv tool update-shell`
> y abre una terminal nueva (así `~/.local/bin` entra en el PATH).

### Desarrollo (modo editable)

```bash
git clone https://github.com/01000001-1001000/PAM-PE && cd PAM-PE
uv sync                          # crea .venv e instala todo, incluido pytest
uv tool install --editable .     # el comando `tareas` refleja tus cambios al instante
uv run pytest                    # lanza las pruebas
```

### Desinstalar

```bash
uv tool uninstall tareas
uv tool list                     # comprueba que ya no aparece
```

## Primeros pasos (¡en una carpeta de pruebas!)

**Prueba siempre en una carpeta de pruebas** hasta que te fíes de tus acciones.

```bash
mkdir ~/pruebas-tareas && cd ~/pruebas-tareas
tareas listar                              # tabla con nombre, tipo, tamaño y fecha
tareas acciones                            # las acciones de ./acciones.json
tareas validar                             # ¿está bien escrito el JSON?
tareas ejecutar ordenar-por-tipo --simular # enseña el plan, NO toca nada
tareas ejecutar ordenar-por-tipo           # lo aplica
```

## Órdenes

| Orden | Qué hace |
|---|---|
| `tareas --help` | Ayuda general (también `tareas ORDEN --help`). |
| `tareas version` | Versión instalada. |
| `tareas listar [CARPETA] [--json]` | Tabla (o JSON) de los ficheros de una carpeta. Por defecto, la actual. |
| `tareas acciones [--json]` | Lista las acciones de `acciones.json` y cuáles usan IA. |
| `tareas validar` | Comprueba `acciones.json` y dice **qué campo falla** (código 3 si es inválido). |
| `tareas ejecutar NOMBRE [CARPETA]` | Ejecuta una acción (pregunta antes de borrar). |
| `tareas ejecutar NOMBRE --simular` | Muestra qué haría **sin tocar nada**. |
| `tareas ejecutar NOMBRE --si` | Confirma sin preguntar (para scripts y tareas programadas). |
| `tareas ejecutar NOMBRE --json` | Informe en JSON. Si la acción pide confirmación, añade `--simular` o `--si` (JSON no puede preguntar). |
| `tareas ia [--probar]` | ¿Está configurada la IA? Con `--probar`, ¿responde? |
| `tareas --config RUTA …` | Opción global: usa otro fichero de acciones (o `TAREAS_CONFIG`). |

Si no indicas `CARPETA`, se usa el `origen` de la acción y, si no tiene, la carpeta actual.

### Códigos de salida

Los scripts y la integración continua deciden con ellos (`echo $?` en bash/zsh,
`echo $LASTEXITCODE` en PowerShell):

| Código | Significado |
|---|---|
| `0` | Todo bien (incluye una cadena que omitió pasos de IA por no haber red). |
| `1` | Fallo al ejecutar: permisos, IA caída, operación cancelada. |
| `2` | Error de uso: acción o carpeta inexistente, opción desconocida. |
| `3` | Configuración inválida (`acciones.json` mal escrito o no encontrado). |

La salida normal va a **stdout** y los avisos y errores a **stderr**, así
`tareas listar --json | jq length` nunca se mezcla con mensajes.

## `acciones.json`

```json
{
  "version": 1,
  "acciones": [
    {
      "nombre": "ordenar-descargas",
      "descripcion": "Mueve los PDF y documentos de Descargas a Documentos/PDF",
      "tipo": "mover",
      "origen": "~/Descargas",
      "filtro": { "extensiones": [".pdf", ".docx"] },
      "destino": "~/Documentos/PDF"
    }
  ]
}
```

Para añadir una acción **no hay que tocar código**: añade un bloque, ejecuta
`tareas validar` y pruébalo con `--simular`. Si te equivocas en una clave
(`"extensions"` en vez de `"extensiones"`), `validar` te dice cuál es y te
sugiere la correcta.

### Campos comunes

| Campo | Obligatorio | Descripción |
|---|---|---|
| `nombre` | sí | Lo que tecleas en `tareas ejecutar NOMBRE`. Minúsculas, números y guiones; único. |
| `descripcion` | sí | Una frase; es lo que ves en `tareas acciones`. |
| `tipo` | sí | Uno de los de la tabla siguiente. |
| `origen` | no | Carpeta de trabajo por defecto (admite `~`). |
| `destino` | según tipo | Carpeta de salida. Si es relativa, cuelga de la carpeta de trabajo. |
| `filtro` | no | Qué ficheros afecta (ver más abajo). Sin filtro = todos. |
| `recursivo` | no | `true` para entrar también en subcarpetas (por defecto `false`). |
| `confirmar` | no | `true` = pregunta antes de aplicar. En `borrar` es `true` por defecto. |

### Tipos de acción

| `tipo` | Qué hace | Campos propios |
|---|---|---|
| `mover` | Mueve los ficheros del filtro a `destino`. | `destino` (obligatorio) |
| `copiar` | Copia los ficheros del filtro a `destino` (copia de seguridad). | `destino` (obligatorio) |
| `borrar` | Borra los ficheros del filtro. **Pide confirmación.** | `filtro` con al menos 1 condición |
| `renombrar` | Renombra con una plantilla. | `plantilla` (obligatorio) |
| `ordenar_por_tipo` | Reparte en subcarpetas (PDF, Imagenes, Comprimidos…). | `categorias` (opcional) |
| `duplicados` | Detecta ficheros con el **mismo contenido** (SHA-256), aunque se llamen distinto. Conserva el más antiguo. | `modo`: `informar` (defecto), `mover` (necesita `destino`) o `borrar` |
| `ia_resumir` | Resume cada PDF/texto con IA y guarda `<fichero>.resumen.md`. | `max_caracteres`, `instruccion` |
| `ia_renombrar` | La IA lee el principio del documento y propone un nombre que diga lo que es. | `max_caracteres` |
| `cadena` | Ejecuta otras acciones **en orden** con una sola orden. | `pasos`: lista de nombres de acciones |

**Plantilla de `renombrar`:** `{fecha:%Y-%m-%d}` (fecha de modificación),
`{n:03}` (contador con ceros), `{ext}` (extensión con punto), `{nombre}` (nombre
original sin extensión). Ejemplo: `"{fecha:%Y-%m-%d}_{n:03}{ext}"` → `2026-10-26_001.jpg`.

**`filtro`** (todas las condiciones se combinan con «y»):

| Campo | Ejemplo | Significado |
|---|---|---|
| `extensiones` | `[".jpg", ".png"]` | Solo esas extensiones (da igual mayúsculas o el punto). |
| `patron` | `".*\\.tmp$"` | Expresión regular sobre el nombre del fichero. |
| `mas_antiguo_que_dias` | `30` | Modificados hace **más** de 30 días. |
| `mayor_que_mb` | `100` | De **más** de 100 MB. |

**Cadenas:** `"pasos": ["limpiar-temporales", "quitar-duplicados", "resumir-documentos", "ordenar-por-tipo"]`.
Cada paso se ejecuta completo antes del siguiente. Con `--simular`, cada paso se
calcula sobre el estado **actual** del disco (los pasos anteriores no se aplican);
el programa lo avisa. No se permiten cadenas dentro de cadenas.

## IA y modo sin red

Las acciones `ia_resumir` e `ia_renombrar` hablan con cualquier servidor
compatible con la API *chat/completions* de OpenAI: los modelos del centro,
Ollama en local, etc.

1. Copia la plantilla: `cp .env.example .env` (Windows: `copy .env.example .env`).
2. Rellena `TAREAS_IA_URL`, `TAREAS_IA_MODELO` y, si hace falta, `TAREAS_IA_CLAVE`.
3. Comprueba: `tareas ia --probar`.

El `.env` está en `.gitignore`: **la clave nunca entra en git**. Las variables
que ya tengas exportadas en tu shell mandan sobre el `.env`.

**Qué pasa si no hay IA o no hay red:**

- Una acción **suelta** con IA termina con código 1 y una línea que explica qué configurar o qué falló.
- En una **cadena**, el paso con IA se **omite con un aviso** y la cadena continúa con los demás pasos (código 0).
- Todas las acciones sin IA funcionan siempre con normalidad.
- Si la IA falla al planificar, **no se ha aplicado nada a medias**.

La salida de la IA nunca se usa sin comprobar: los nombres propuestos se «sanean»
(sin `/`, `..`, tildes ni caracteres prohibidos en Windows) y, antes de nada,
`--simular` te enseña qué nombre propone para cada fichero.

> Los resúmenes y nombres los genera un modelo: **revísalos** antes de fiarte.

## Seguridad

- **`--simular`** siempre primero; borrar pide confirmación `[s/N]` (Intro = no).
- **Nunca se sobrescribe:** si el destino existe se usa `nombre_1.ext`, `nombre_2.ext`…
- Se ignoran los ficheros **ocultos** (`.env`…) y los **enlaces simbólicos**.
- Una acción que puede borrar **se niega** a ejecutarse en la raíz del disco o en toda tu carpeta personal.
- La plantilla de `renombrar` rechaza campos desconocidos y caracteres prohibidos al **cargar** el JSON.
- Las claves de IA no se escriben jamás en mensajes de error ni en pantalla.

## Estructura del proyecto

```
cli-tareas/
├── pyproject.toml          # dependencias y entry point: tareas = "tareas.cli:app"
├── acciones.json           # TUS acciones (ejemplo incluido: adáptalo)
├── .env.example            # plantilla de configuración de la IA (sin claves)
├── docs/
│   ├── spec.md             # especificación de 10 líneas
│   └── adr/0001-configuracion-externa.md
├── src/tareas/
│   ├── cli.py              # interfaz Typer + Rich: habla con la persona
│   ├── motor.py            # planificar → mostrar → confirmar → aplicar
│   ├── acciones.py         # clases Accion (+ fábricas desde el JSON)
│   ├── filtros.py          # qué ficheros afecta una acción
│   ├── config.py           # lee y VALIDA acciones.json
│   ├── validacion.py       # validaciones con mensajes claros
│   ├── plan.py             # Operacion, Plan, Informe, Contexto
│   ├── ia.py               # proveedor de IA y modo sin red
│   ├── lector.py           # extrae texto de PDF y ficheros de texto
│   ├── utilidades.py       # tamaños legibles, nombres seguros, hashes
│   └── errores.py          # excepciones propias con código de salida
├── tests/                  # pytest: camino feliz + casos feos
└── .github/workflows/ci.yml  # pruebas en Ubuntu, Windows y macOS
```

**Regla de oro del diseño:** `cli.py` habla con la persona; `motor.py` y
`acciones.py` hacen el trabajo sin saber nada de Typer; `config.py` desconfía del JSON.
Una acción **solo planifica** (lee del disco, devuelve un `Plan`); el motor es
quien lo aplica. Por eso `--simular` es seguro por construcción.

## Pruebas

```bash
uv run pytest            # todas
uv run pytest -k feo     # solo los casos feos
```

Las pruebas nunca tocan tus ficheros: trabajan en carpetas temporales y la IA se
sustituye por una falsa (o por un servidor HTTP local) sin usar internet. Cubren
el camino feliz de cada acción y, entre otros, estos casos feos: JSON mal
escrito, carpeta inexistente, nombres con tildes y espacios, destino ya
existente, permisos denegados, usuario que cancela, IA sin configurar, servidor
sin red, respuestas ilegibles de la IA y errores internos. GitHub Actions las
ejecuta en Linux, Windows y macOS en cada `push` y Pull Request.

## Probar la instalación en otro sistema

1. Pide a alguien (mejor con otro sistema operativo) que siga **solo este README**.
2. `uv tool install git+https://github.com/01000001-1001000/PAM-PE/` y `tareas --help` / `tareas version` desde otra carpeta.
3. Crea una carpeta de pruebas con ficheros de ejemplo y lanza cada acción con `--simular` y luego de verdad.
4. Prueba un nombre con tildes y espacios (`Apuntes de Física.pdf`) y una ruta con `~`.
5. Rompe a propósito `acciones.json`: `tareas validar` debe decir qué falla y salir con código 3.
6. Desinstala y comprueba que `tareas` ya no existe.

## Versiones

Consulta el [CHANGELOG](CHANGELOG.md). La versión vive solo en
`src/tareas/__init__.py` (`__version__`) y `tareas version` la muestra.
