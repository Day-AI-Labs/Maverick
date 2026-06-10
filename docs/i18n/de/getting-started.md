<!-- Von der Community gepflegte Übersetzung von docs/getting-started.md (Quell-Commit: 001740b) — die englische Version ist maßgeblich. -->

# Erste Schritte

## Installation

Der sicherste Weg im Terminal ist, das veröffentlichte Paket mit pipx zu installieren, statt ein entferntes Bootstrap-Skript auszuführen:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Wenn Sie das Desktop-Bootstrap ohne Voraussetzungen benötigen, laden Sie `deploy/desktop/install.sh` oder `deploy/desktop/install.ps1` von einem Commit oder Release herunter, dem Sie vertrauen, prüfen Sie das Skript und setzen Sie `MAVERICK_REF` auf einen vollständigen, 40 Zeichen langen Commit-SHA. Veränderliche Branch- oder Tag-Referenzen lehnen die Skripte standardmäßig ab.

Das PyPI-Paket heißt `maverick-agent` (der Name `maverick` ist bereits von einem fremden Projekt belegt). Das Extra `[installer]` installiert den Assistenten in dieselbe pipx-Umgebung wie den Kernel, damit `maverick init` aufgelöst werden kann.

Aus dem Quellcode, während Sie daran entwickeln:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Erster Start

```bash
maverick init
```

Der Assistent dauert etwa 2 Minuten. Er schreibt `~/.maverick/config.toml` und `~/.maverick/.env`.

Danach:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Dem Schwarm beim Zerlegen zusehen

Führen Sie `maverick monitor` in einem zweiten Terminal aus. Der Orchestrator plant das Ziel und startet dann spezialisierte Sub-Agenten, die parallel arbeiten — hier grenzt ein Researcher die API ein, ein Coder schreibt das Tool, und ein Verifier führt es aus:

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

Wenn alles fertig ist:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Pausieren / Fortsetzen

Braucht der Schwarm etwas, das nur Sie beantworten können, pausiert er und stellt eine Frage in die Warteschlange:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Ziele überleben Neustarts. Sie können Ihren Laptop zuklappen und morgen weitermachen.

## Modelle oder Provider wechseln

Führen Sie den Assistenten jederzeit erneut aus:

```bash
maverick init
```

Oder bearbeiten Sie `~/.maverick/config.toml` direkt. Der Abschnitt `[models]` ordnet jeder Agentenrolle eine Zeichenkette der Form `provider:model-id` zu. Das Schema ist in [`configuration.md`](./configuration.md) beschrieben.

## Wo die Daten liegen

| Datei | Inhalt |
|---|---|
| `~/.maverick/config.toml` | Ihre Konfiguration (Deployment, Modelle, Sicherheit, Budget) |
| `~/.maverick/.env` | API-Schlüssel (chmod 600) |
| `~/.maverick/world.db` | Persistentes Weltmodell: Ziele, Fakten, Episoden |
| `~/.maverick/skills/` | Automatisch destillierte SKILL.md-Dateien aus erfolgreichen Läufen |
| `~/maverick-workspace/` | Standard-Arbeitsverzeichnis der Sandbox |

Alles bleibt lokal. Außer Ihren Prompts an das von Ihnen gewählte Cloud-LLM wird nichts hochgeladen.
