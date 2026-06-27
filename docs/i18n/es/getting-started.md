<!-- Traducción mantenida por la comunidad. Archivo de origen: docs/getting-started.md (commit 00d6097) — la versión en inglés es la autorizada. -->

# Primeros pasos

## Instalación

La vía más segura desde la terminal es instalar el paquete publicado con pipx, en lugar de ejecutar un script de arranque remoto:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Si necesitas el arranque de escritorio sin requisitos previos, descarga `deploy/desktop/install.sh` o `deploy/desktop/install.ps1` desde un commit o una release en los que confíes, verifica el script y establece `MAVERICK_REF` con el SHA completo de 40 caracteres de un commit. Por defecto, los scripts rechazan referencias mutables a ramas o etiquetas.

El paquete de PyPI es `maverick-agent` (el nombre `maverick` está ocupado por otro proyecto). El extra `[installer]` instala el asistente en el mismo entorno de pipx que el núcleo, de modo que `maverick init` se pueda resolver.

Desde el código fuente, mientras desarrollas:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Primera ejecución

```bash
maverick init
```

El asistente tarda unos 2 minutos. Escribe `~/.maverick/config.toml` y `~/.maverick/.env`.

Después:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Observa cómo el enjambre descompone el objetivo

Ejecuta `maverick monitor` en una segunda terminal. El orquestador planifica el objetivo y luego lanza subagentes especialistas que trabajan en paralelo: aquí un investigador determina la API, un programador escribe la herramienta y un verificador la ejecuta:

```
Goal #1 active  2m elapsed
Build a CLI that emails me a digest of today's top Hacker News stories

Plan tree
  ├─        done  #2 Research the Hacker News Firebase API
  ├─      active  #3 Write the digest CLI (fetch + format + send)
  ├─      active  #4 Verify it runs and emails a sample digest
  ├─     pending  #5 Write a short usage README

Latest episode #7 (running)  $0.0431  in=18,204 out=2,910 tools=11

Recent activity
  4s ago [researcher] decision: top stories live at /v0/topstories.json, then /v0/item/<id>.json
  3s ago [coder] tool_call: write_file hn_digest.py (118 lines)
  1s ago [verifier] tool_call: run "python hn_digest.py --dry-run" -> printed 10 stories

Cumulative spend on this DB: $0.21
```

Al terminar:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Pausar / reanudar

Si el enjambre necesita algo que solo tú puedes responder, se pausa y pone una pregunta en cola:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Los objetivos sobreviven a los reinicios. Puedes cerrar el portátil y volver mañana.

## Crea tu propio especialista a partir de una tarea observada

No tienes que describir un trabajo con palabras: puedes mostrarlo. Captura un
registro ordenado de alguien haciendo el trabajo (las acciones que realizó y
cualquier narración del porqué) como JSONL o texto simple con prefijos, y luego
entrega el archivo a Lightwork:

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

Esto analiza la demostración, induce un borrador de especialista, te muestra el
flujo de trabajo derivado y espera tu aprobación antes de guardarlo. Los secretos
se ocultan en la puerta, y el borrador hereda el mismo límite de capacidades y
análisis de persona que recibe un pack descrito: nada se activa sin tu sí.
Opciones útiles:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` reproduce de forma determinista los pasos observados (las herramientas
= las que usó la persona); omítelo para dejar que el modelo proponga a partir de
la transcripción.

El mismo flujo de fábrica de agentes se ejecuta cuando construyes un pack de
forma conversacional:

```bash
maverick onboard
```

Al aprobarlo, `onboard` ahora aprovisiona el pack: instala las skills del
catálogo que necesita su flujo de trabajo y sintetiza cualquier herramienta
declarada que no esté incorporada, de modo que un especialista recién aprobado
está equipado para hacer su trabajo desde la primera ejecución. (Este paso
respeta la configuración `[self_learning]` / `provision_packs` y nunca amplía el
sobre limitado del pack.)

## Cambiar de modelos o proveedores

Vuelve a ejecutar el asistente en cualquier momento:

```bash
maverick init
```

O edita `~/.maverick/config.toml` directamente. La sección `[models]` asigna a cada rol de agente una cadena `provider:model-id`. Consulta [`configuration.md`](../../configuration.md) para ver el esquema.

## Dónde se guardan los datos

| Archivo | Qué contiene |
|---|---|
| `~/.maverick/config.toml` | Tu configuración (despliegue, modelos, seguridad, presupuesto) |
| `~/.maverick/.env` | Claves de API (chmod 600) |
| `~/.maverick/world.db` | Modelo del mundo persistente: objetivos, hechos, episodios |
| `~/.maverick/skills/` | Archivos SKILL.md destilados automáticamente de las ejecuciones con éxito |
| `~/maverick-workspace/` | Directorio de trabajo por defecto del sandbox |
| `~/.maverick/learned-skills/` | Skills destiladas por los bucles de aprendizaje |
| `~/.maverick/dreams/` | Conocimientos consolidados, cola de ensayo, instantáneas de aprendizaje |

Todo es local. No se sube nada, salvo tus prompts al LLM en la nube que hayas elegido.

Una vez que tengas unas cuantas ejecuciones a tus espaldas, la superficie de
aprendizaje son cuatro comandos: `maverick dream` (consolida la experiencia),
`maverick hindsight` (¿el aprendizaje ayudó o empeoró?), `maverick proof`
(entregables, costes evitados, ROI) y `maverick domains-lint` (audita el catálogo
de especialistas de 2,020 agentes), además de `maverick domains-audit` (postura de
gobernanza: qué puede alcanzar cada agente, qué deniega y qué rechaza) y
`maverick domains-eval --check` (casos dorados de comportamiento).
