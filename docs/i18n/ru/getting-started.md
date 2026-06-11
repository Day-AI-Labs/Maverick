<!-- Поддерживаемый сообществом перевод docs/getting-started.md (исходный коммит: 001740b) — английская версия является основной. -->

# Начало работы

## Установка

Самый безопасный способ установки из терминала — поставить опубликованный пакет через pipx, а не выполнять удалённый bootstrap-скрипт:

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

Если вам нужен десктопный bootstrap без предварительных требований, скачайте `deploy/desktop/install.sh` или `deploy/desktop/install.ps1` из коммита или релиза, которому вы доверяете, проверьте скрипт и задайте в `MAVERICK_REF` полный 40-символьный SHA коммита. По умолчанию скрипты отклоняют изменяемые ссылки на ветки и теги.

Пакет в PyPI называется `maverick-agent` (имя `maverick` занято посторонним проектом). Экстра `[installer]` устанавливает мастер настройки в то же окружение pipx, что и ядро, поэтому команда `maverick init` будет доступна.

Из исходного кода, во время разработки:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## Первый запуск

```bash
maverick init
```

Мастер настройки занимает около 2 минут. Он записывает `~/.maverick/config.toml` и `~/.maverick/.env`.

Затем:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## Наблюдайте, как рой декомпозирует цель

Запустите `maverick monitor` во втором терминале. Оркестратор планирует цель, а затем порождает специализированных субагентов, работающих параллельно: здесь исследователь разбирается с API, кодер пишет инструмент, а верификатор его запускает:

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

Когда всё готово:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## Пауза и возобновление

Если рою нужно что-то, на что можете ответить только вы, он приостанавливается и ставит вопрос в очередь:

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

Цели переживают перезапуски. Вы можете закрыть ноутбук и вернуться завтра.

## Смена моделей и провайдеров

Перезапускайте мастер настройки в любой момент:

```bash
maverick init
```

Или отредактируйте `~/.maverick/config.toml` напрямую. Секция `[models]` сопоставляет каждой роли агента строку вида `provider:model-id`. Схема описана в [`configuration.md`](./configuration.md).

## Где хранятся данные

| Файл | Что это |
|---|---|
| `~/.maverick/config.toml` | Ваша конфигурация (развёртывание, модели, безопасность, бюджет) |
| `~/.maverick/.env` | API-ключи (chmod 600) |
| `~/.maverick/world.db` | Персистентная модель мира: цели, факты, эпизоды |
| `~/.maverick/skills/` | Файлы SKILL.md, автоматически извлечённые из успешных запусков |
| `~/maverick-workspace/` | Рабочий каталог песочницы по умолчанию |

Все данные хранятся локально. Никуда ничего не передаётся, кроме ваших промптов выбранной вами облачной LLM.
