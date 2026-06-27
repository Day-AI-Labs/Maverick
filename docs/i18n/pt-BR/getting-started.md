<!-- Tradução mantida pela comunidade de docs/getting-started.md (commit de origem: 00d6097) — a versão em inglês é a oficial. -->

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

## Crie seu próprio especialista a partir de uma tarefa observada

Você não precisa descrever um trabalho com palavras — você pode demonstrá-lo.
Capture um registro ordenado de alguém realizando o trabalho (as ações que a
pessoa executou e qualquer narração do porquê) como JSONL ou texto simples com
prefixos e, em seguida, entregue o arquivo ao Lightwork:

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

Isso analisa a demonstração, induz um rascunho de especialista, mostra a você o
fluxo de trabalho derivado e aguarda sua aprovação antes de salvar. Os segredos
são removidos logo na entrada, e o rascunho herda o mesmo limite de capacidades
e a mesma varredura de persona que um pacote descrito recebe — nada é ativado
sem o seu sim. Flags úteis:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` espelha de forma determinística os passos observados (as ferramentas
= o que a pessoa usou); omita-o para deixar o modelo propor a partir da
transcrição.

O mesmo fluxo de fábrica de agentes é executado quando você cria um pacote de
forma conversacional:

```bash
maverick onboard
```

Após a aprovação, o `onboard` agora provisiona o pacote — ele instala as skills
do catálogo de que o fluxo de trabalho precisa e sintetiza quaisquer ferramentas
declaradas que não sejam nativas, de modo que um especialista recém-aprovado
esteja equipado para fazer seu trabalho desde a primeira execução. (Essa etapa
respeita a configuração `[self_learning]` / `provision_packs` e nunca amplia o
envelope limitado do pacote.)

## Trocar de modelos ou provedores

Execute o assistente novamente a qualquer momento:

```bash
maverick init
```

Ou edite `~/.maverick/config.toml` diretamente. A seção `[models]` mapeia cada papel de agente para uma string `provider:model-id`. Consulte [`configuration.md`](../../configuration.md) para ver o esquema.

## Onde os dados ficam

| Arquivo | O que é |
|---|---|
| `~/.maverick/config.toml` | Sua configuração (implantação, modelos, segurança, orçamento) |
| `~/.maverick/.env` | Chaves de API (chmod 600) |
| `~/.maverick/world.db` | Modelo de mundo persistente: objetivos, fatos, episódios |
| `~/.maverick/skills/` | Arquivos SKILL.md destilados automaticamente de execuções bem-sucedidas |
| `~/maverick-workspace/` | Diretório de trabalho padrão do sandbox |
| `~/.maverick/learned-skills/` | Skills destiladas pelos loops de aprendizado |
| `~/.maverick/dreams/` | Insights consolidados, fila de ensaio, snapshots de aprendizado |

Tudo fica local. Nada é enviado para fora, exceto seus prompts para o LLM na nuvem que você escolheu.

Depois de algumas execuções acumuladas, a superfície de aprendizado se resume a
quatro comandos: `maverick dream` (consolidar a experiência), `maverick hindsight`
(o aprendizado ajudou ou regrediu?), `maverick proof` (entregas, custo evitado,
ROI) e `maverick domains-lint` (auditar o catálogo de especialistas de 2,020
agentes), além de `maverick domains-audit` (postura de governança: o que cada
agente pode acessar, nega e recusa) e `maverick domains-eval --check` (casos de
referência comportamentais).
