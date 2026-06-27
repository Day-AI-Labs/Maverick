<!-- Traduction maintenue par la communauté de docs/getting-started.md (commit source : 00d6097) — la version anglaise fait foi. -->

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

## Construire votre propre spécialiste à partir d'une tâche observée

Vous n'êtes pas obligé de décrire un travail avec des mots — vous pouvez le
montrer. Capturez un enregistrement ordonné de quelqu'un en train d'accomplir le
travail (les actions effectuées et toute explication du pourquoi) sous forme de
JSONL ou de simple texte préfixé, puis confiez le fichier à Lightwork :

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

Cela analyse la démonstration, induit un brouillon de spécialiste, vous montre le
workflow dérivé et attend votre approbation avant de l'enregistrer. Les secrets
sont expurgés dès l'entrée, et le brouillon hérite de la même limitation de
capacités et de la même analyse de persona qu'un pack décrit — rien ne s'active
sans votre accord. Options utiles :

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` reproduit les étapes observées de manière déterministe (les outils =
ce que la personne a utilisé) ; omettez-le pour laisser le modèle faire des
propositions à partir de la transcription.

Le même flux d'usine à agents s'exécute lorsque vous construisez un pack de
manière conversationnelle :

```bash
maverick onboard
```

Une fois approuvé, `onboard` provisionne désormais le pack — il installe les
compétences du catalogue dont son workflow a besoin et synthétise tous les outils
déclarés qui ne sont pas intégrés, de sorte qu'un spécialiste fraîchement
approuvé est équipé pour faire son travail dès la première exécution. (Cette
étape respecte la configuration `[self_learning]` / `provision_packs` et n'élargit
jamais l'enveloppe verrouillée du pack.)

## Changer de modèles ou de fournisseurs

Relancez l'assistant à tout moment :

```bash
maverick init
```

Ou modifiez directement `~/.maverick/config.toml`. La section `[models]` associe chaque rôle d'agent à une chaîne `provider:model-id`. Consultez [`configuration.md`](../../configuration.md) pour le schéma.

## Où sont stockées les données

| Fichier | Contenu |
|---|---|
| `~/.maverick/config.toml` | Votre configuration (déploiement, modèles, sécurité, budget) |
| `~/.maverick/.env` | Clés d'API (chmod 600) |
| `~/.maverick/world.db` | Modèle du monde persistant : objectifs, faits, épisodes |
| `~/.maverick/skills/` | Fichiers SKILL.md distillés automatiquement à partir des exécutions réussies |
| `~/maverick-workspace/` | Répertoire de travail par défaut du bac à sable |
| `~/.maverick/learned-skills/` | Compétences distillées par les boucles d'apprentissage |
| `~/.maverick/dreams/` | Aperçus consolidés, file de répétition, instantanés d'apprentissage |

Tout reste en local. Rien n'est envoyé, hormis vos prompts au LLM cloud que vous avez choisi.

Une fois que vous avez quelques exécutions derrière vous, la surface
d'apprentissage tient en quatre commandes : `maverick dream` (consolider
l'expérience), `maverick hindsight` (l'apprentissage a-t-il aidé ou régressé ?),
`maverick proof` (livrables, coûts évités, ROI) et `maverick domains-lint`
(auditer le catalogue de spécialistes à 2,020 agents), auxquelles s'ajoutent
`maverick domains-audit` (posture de gouvernance : ce que chaque agent peut
atteindre, refuse et rejette) et `maverick domains-eval --check` (cas de
référence comportementaux).
