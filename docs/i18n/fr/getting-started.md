<!-- Traduction maintenue par la communauté de docs/getting-started.md (commit source : 001740b) — la version anglaise fait foi. -->

# Premiers pas

## Installation

La méthode la plus sûre en terminal consiste à installer le paquet publié avec pipx, plutôt qu'à exécuter un script d'amorçage distant :

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Si vous avez besoin de l'amorçage bureau sans prérequis, téléchargez `deploy/desktop/install.sh` ou `deploy/desktop/install.ps1` depuis un commit ou une release de confiance, vérifiez le script, puis donnez à `MAVERICK_REF` la valeur d'un SHA de commit complet de 40 caractères. Par défaut, les scripts rejettent les références mutables vers des branches ou des tags.

Le paquet PyPI s'appelle `maverick-agent` (le nom `maverick` est squatté). L'extra `[installer]` installe l'assistant dans le même environnement pipx que le noyau, afin que `maverick init` soit disponible.

Depuis les sources, pendant le développement :

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Premier lancement

```bash
maverick init
```

L'assistant prend environ 2 minutes. Il écrit `~/.maverick/config.toml` et `~/.maverick/.env`.

Ensuite :

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Regarder l'essaim décomposer l'objectif

Lancez `maverick monitor` dans un second terminal. L'orchestrateur planifie l'objectif, puis lance des sous-agents spécialisés qui travaillent en parallèle — ici, un chercheur identifie l'API, un codeur écrit l'outil et un vérificateur l'exécute :

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

Une fois terminé :

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Mettre en pause / reprendre

Si l'essaim a besoin d'une information que vous seul pouvez fournir, il se met en pause et place une question en file d'attente :

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Les objectifs survivent aux redémarrages. Vous pouvez fermer votre ordinateur portable et revenir demain.

## Changer de modèles ou de fournisseurs

Relancez l'assistant à tout moment :

```bash
maverick init
```

Ou modifiez directement `~/.maverick/config.toml`. La section `[models]` associe chaque rôle d'agent à une chaîne `provider:model-id`. Consultez [`configuration.md`](./configuration.md) pour le schéma.

## Où sont stockées les données

| Fichier | Contenu |
|---|---|
| `~/.maverick/config.toml` | Votre configuration (déploiement, modèles, sécurité, budget) |
| `~/.maverick/.env` | Clés d'API (chmod 600) |
| `~/.maverick/world.db` | Modèle du monde persistant : objectifs, faits, épisodes |
| `~/.maverick/skills/` | Fichiers SKILL.md distillés automatiquement à partir des exécutions réussies |
| `~/maverick-workspace/` | Répertoire de travail par défaut du bac à sable |

Tout reste en local. Rien n'est envoyé, hormis vos prompts au LLM cloud que vous avez choisi.
