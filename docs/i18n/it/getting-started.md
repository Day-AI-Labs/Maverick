<!-- Traduzione mantenuta dalla community di docs/getting-started.md (commit di origine: 00d6097) — la versione inglese è quella di riferimento. -->

# Primi passi

## Installazione

Il percorso più sicuro da terminale è installare il pacchetto pubblicato con pipx, invece di eseguire uno script di bootstrap remoto:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Se ti serve il bootstrap desktop senza prerequisiti, scarica `deploy/desktop/install.sh` o `deploy/desktop/install.ps1` da un commit o da una release di cui ti fidi, verifica lo script e imposta `MAVERICK_REF` sullo SHA completo di 40 caratteri di un commit. Per impostazione predefinita gli script rifiutano i riferimenti mutabili a branch o tag.

Il pacchetto PyPI è `maverick-agent` (il nome `maverick` è già occupato da altri). L'extra `[installer]` installa la procedura guidata nello stesso ambiente pipx del kernel, in modo che `maverick init` sia disponibile.

Dai sorgenti, durante lo sviluppo:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Primo avvio

```bash
maverick init
```

La procedura guidata richiede circa 2 minuti e scrive `~/.maverick/config.toml` e `~/.maverick/.env`.

Poi:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Osserva lo sciame scomporre l'obiettivo

Esegui `maverick monitor` in un secondo terminale. L'orchestratore pianifica l'obiettivo, poi avvia sotto-agenti specializzati che lavorano in parallelo: qui un ricercatore individua l'API, un programmatore scrive lo strumento e un verificatore lo esegue:

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

Al termine:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Mettere in pausa / riprendere

Se lo sciame ha bisogno di qualcosa a cui solo tu puoi rispondere, si mette in pausa e accoda una domanda:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Gli obiettivi sopravvivono ai riavvii. Puoi chiudere il portatile e tornare domani.

## Costruire il tuo specialista da un'attività osservata

Non sei obbligato a descrivere un lavoro a parole: puoi mostrarlo. Cattura una
registrazione ordinata di qualcuno che svolge il lavoro (le azioni che ha
compiuto e qualsiasi spiegazione del perché) come JSONL o come semplice testo con
prefissi, poi consegna il file a Lightwork:

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

Questo analizza la dimostrazione, induce una bozza di specialista, ti mostra il
flusso di lavoro derivato e attende la tua approvazione prima di salvare. I
segreti vengono oscurati all'ingresso e la bozza eredita lo stesso vincolo sulle
capacità e la stessa scansione della persona di un pack descritto: nulla si
attiva senza il tuo consenso. Flag utili:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` rispecchia in modo deterministico i passaggi osservati (gli strumenti
= quelli usati dalla persona); ometti il flag per lasciare che il modello proponga
a partire dalla trascrizione.

Lo stesso flusso di agent-factory si avvia quando costruisci un pack in modo
conversazionale:

```bash
maverick onboard
```

Una volta approvato, `onboard` ora effettua il provisioning del pack: installa le
skill del catalogo di cui il suo flusso di lavoro ha bisogno e sintetizza
qualsiasi strumento dichiarato che non sia già integrato, in modo che uno
specialista appena approvato sia attrezzato per svolgere il proprio compito fin
dalla prima esecuzione. (Questo passaggio rispetta la configurazione
`[self_learning]` / `provision_packs` e non amplia mai l'envelope vincolato del
pack.)

## Cambiare modelli o provider

Riesegui la procedura guidata in qualsiasi momento:

```bash
maverick init
```

Oppure modifica direttamente `~/.maverick/config.toml`. La sezione `[models]` associa ogni ruolo di agente a una stringa `provider:model-id`. Per lo schema consulta [`configuration.md`](../../configuration.md).

## Dove si trovano i dati

| File | Contenuto |
|---|---|
| `~/.maverick/config.toml` | La tua configurazione (deployment, modelli, sicurezza, budget) |
| `~/.maverick/.env` | Chiavi API (chmod 600) |
| `~/.maverick/world.db` | Modello del mondo persistente: obiettivi, fatti, episodi |
| `~/.maverick/skills/` | File SKILL.md distillati automaticamente dalle esecuzioni riuscite |
| `~/maverick-workspace/` | Directory di lavoro predefinita della sandbox |
| `~/.maverick/learned-skills/` | Skill distillate dai cicli di apprendimento |
| `~/.maverick/dreams/` | Insight consolidati, coda di prove, snapshot dell'apprendimento |

Tutto resta in locale. Non viene caricato nulla, tranne i tuoi prompt verso l'LLM cloud che hai scelto.

Una volta che avrai alle spalle alcune esecuzioni, la superficie di apprendimento
si riduce a quattro comandi: `maverick dream` (consolidare l'esperienza),
`maverick hindsight` (l'apprendimento ha aiutato o peggiorato?), `maverick proof`
(risultati prodotti, costo evitato, ROI) e `maverick domains-lint` (verifica del
catalogo di specialisti da 2,020 agenti), oltre a `maverick domains-audit`
(postura di governance: cosa ogni agente può raggiungere, nega e rifiuta) e
`maverick domains-eval --check` (casi golden comportamentali).
