<!-- これは docs/getting-started.md（翻訳元コミット: 001740b）のコミュニティによって維持されている翻訳です。英語版が正式版です。 -->

# はじめに

## インストール

ターミナルからの最も安全なインストール方法は、リモートのブートストラップスクリプトを実行するのではなく、公開済みパッケージを pipx でインストールすることです。

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

前提条件なしで使えるデスクトップ向けブートストラップが必要な場合は、信頼できるコミットまたはリリースから `deploy/desktop/install.sh` か `deploy/desktop/install.ps1` をダウンロードして検証し、`MAVERICK_REF` に 40 文字の完全なコミット SHA を設定してください。これらのスクリプトは、デフォルトでは可変のブランチ参照やタグ参照を拒否します。

PyPI のパッケージ名は `maverick-agent` です（`maverick` という名前は別の登録者に取られています）。`[installer]` エクストラを付けると、ウィザードがカーネルと同じ pipx 環境にインストールされ、`maverick init` が実行できるようになります。

開発中にソースから使う場合:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## 初回実行

```bash
maverick init
```

ウィザードの所要時間は 2 分ほどです。`~/.maverick/config.toml` と `~/.maverick/.env` を書き出します。

次に、以下を実行します。

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## スウォームが目標を分解する様子を見る

2 つ目のターミナルで `maverick monitor` を実行します。オーケストレーターが目標の計画を立て、並列で動作する専門のサブエージェントを起動します。この例では、リサーチャーが API を特定し、コーダーがツールを書き、ベリファイアがそれを実行して確認します。

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

完了したら:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## 一時停止と再開

あなたにしか答えられないことが必要になると、スウォームは一時停止し、質問をキューに入れます。

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

目標は再起動後も保持されます。ノート PC を閉じて、明日また戻ってきても問題ありません。

## モデルやプロバイダーの変更

ウィザードはいつでも再実行できます。

```bash
maverick init
```

または、`~/.maverick/config.toml` を直接編集してください。`[models]` セクションは、各エージェントロールを `provider:model-id` 形式の文字列に対応付けます。スキーマの詳細は [`configuration.md`](./configuration.md) を参照してください。

## データの保存場所

| ファイル | 内容 |
|---|---|
| `~/.maverick/config.toml` | 設定（デプロイ、モデル、安全性、予算） |
| `~/.maverick/.env` | API キー（chmod 600） |
| `~/.maverick/world.db` | 永続的なワールドモデル: 目標、事実、エピソード |
| `~/.maverick/skills/` | 成功した実行から自動的に蒸留された SKILL.md ファイル |
| `~/maverick-workspace/` | サンドボックスのデフォルト作業ディレクトリ |

すべてのデータはローカルに保存されます。選択したクラウド LLM に送信されるプロンプトを除き、何もアップロードされません。
