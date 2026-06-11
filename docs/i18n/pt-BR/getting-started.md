<!-- Tradução mantida pela comunidade de docs/getting-started.md (commit de origem: 001740b) — a versão em inglês é a oficial. -->

# Primeiros passos

## Instalação

O caminho mais seguro pelo terminal é instalar o pacote publicado com o pipx, em vez de executar um script de bootstrap remoto:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Se você precisar do bootstrap de desktop sem pré-requisitos, baixe `deploy/desktop/install.sh` ou `deploy/desktop/install.ps1` de um commit ou release em que você confie, verifique o script e defina `MAVERICK_REF` com o SHA completo de 40 caracteres de um commit. Por padrão, os scripts rejeitam referências mutáveis de branch ou tag.

O pacote no PyPI é `maverick-agent` (o nome `maverick` já está ocupado por outro projeto). O extra `[installer]` instala o assistente no mesmo ambiente pipx do kernel, para que `maverick init` funcione.

A partir do código-fonte, durante o desenvolvimento:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Primeira execução

```bash
maverick init
```

O assistente leva cerca de 2 minutos. Ele grava `~/.maverick/config.toml` e `~/.maverick/.env`.

Em seguida:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Veja o enxame decompor o objetivo

Execute `maverick monitor` em um segundo terminal. O orquestrador planeja o objetivo e, em seguida, cria subagentes especialistas que trabalham em paralelo — aqui, um pesquisador identifica a API, um programador escreve a ferramenta e um verificador a executa:

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

Ao terminar:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Pausar / retomar

Se o enxame precisar de algo que só você pode responder, ele pausa e coloca uma pergunta na fila:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Os objetivos sobrevivem a reinicializações. Você pode fechar o notebook e voltar amanhã.

## Trocar de modelos ou provedores

Execute o assistente novamente a qualquer momento:

```bash
maverick init
```

Ou edite `~/.maverick/config.toml` diretamente. A seção `[models]` mapeia cada papel de agente para uma string `provider:model-id`. Consulte [`configuration.md`](./configuration.md) para ver o esquema.

## Onde os dados ficam

| Arquivo | O que é |
|---|---|
| `~/.maverick/config.toml` | Sua configuração (implantação, modelos, segurança, orçamento) |
| `~/.maverick/.env` | Chaves de API (chmod 600) |
| `~/.maverick/world.db` | Modelo de mundo persistente: objetivos, fatos, episódios |
| `~/.maverick/skills/` | Arquivos SKILL.md destilados automaticamente de execuções bem-sucedidas |
| `~/maverick-workspace/` | Diretório de trabalho padrão do sandbox |

Tudo fica local. Nada é enviado para fora, exceto seus prompts para o LLM na nuvem que você escolheu.
