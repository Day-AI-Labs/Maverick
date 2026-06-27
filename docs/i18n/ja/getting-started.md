<!-- これは docs/getting-started.md（翻訳元コミット: 00d6097）のコミュニティによって維持されている翻訳です。英語版が正式版です。 -->

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

## 観察したタスクから自分専用のスペシャリストを作る

仕事を言葉で説明する必要はありません。実際にやって見せることもできます。誰かが作業をしている様子（取った行動と、その理由についての説明）を順序付きの記録として JSONL かシンプルな接頭辞付きテキストで取得し、そのファイルを Lightwork に渡してください。

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

これはデモンストレーションを解析し、ドラフトのスペシャリストを生成し、導出されたワークフローを表示して、保存する前にあなたの承認を待ちます。シークレットは入り口で秘匿化され、ドラフトは説明から作成したパックと同じ機能の制限とペルソナスキャンを引き継ぎます。あなたが「はい」と言わない限り、何も有効化されません。便利なフラグ:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm` は観察されたステップを決定論的にそのまま再現します（ツール = その人が使ったもの）。これを外すと、モデルがトランスクリプトから提案できるようになります。

同じエージェントファクトリーのフローは、対話形式でパックを構築するときにも実行されます。

```bash
maverick onboard
```

承認すると、`onboard` はパックをプロビジョニングするようになりました。ワークフローに必要なカタログスキルをインストールし、ビルトインではない宣言済みツールを合成するので、承認されたばかりのスペシャリストは最初の実行からその仕事をこなす準備が整っています。（このステップは `[self_learning]` / `provision_packs` の設定を尊重し、パックの制限された範囲を広げることは決してありません。）

## モデルやプロバイダーの変更

ウィザードはいつでも再実行できます。

```bash
maverick init
```

または、`~/.maverick/config.toml` を直接編集してください。`[models]` セクションは、各エージェントロールを `provider:model-id` 形式の文字列に対応付けます。スキーマの詳細は [`configuration.md`](../../configuration.md) を参照してください。

## データの保存場所

| ファイル | 内容 |
|---|---|
| `~/.maverick/config.toml` | 設定（デプロイ、モデル、安全性、予算） |
| `~/.maverick/.env` | API キー（chmod 600） |
| `~/.maverick/world.db` | 永続的なワールドモデル: 目標、事実、エピソード |
| `~/.maverick/skills/` | 成功した実行から自動的に蒸留された SKILL.md ファイル |
| `~/maverick-workspace/` | サンドボックスのデフォルト作業ディレクトリ |
| `~/.maverick/learned-skills/` | 学習ループによって蒸留されたスキル |
| `~/.maverick/dreams/` | 統合された知見、リハーサルキュー、学習スナップショット |

すべてのデータはローカルに保存されます。選択したクラウド LLM に送信されるプロンプトを除き、何もアップロードされません。

ある程度の実行を重ねたら、学習面は 4 つのコマンドに集約されます。`maverick dream`（経験を統合する）、`maverick hindsight`（学習は役立ったか、それとも後退したか？）、`maverick proof`（成果物、回避できたコスト、ROI）、そして `maverick domains-lint`（2,020 エージェントのスペシャリストカタログを監査する）に加えて、`maverick domains-audit`（ガバナンス態勢: 各エージェントが何にアクセスでき、何を拒否し、何を却下するか）と `maverick domains-eval --check`（振る舞いのゴールデンケース）です。
