<!-- docs/getting-started.md(원본 커밋: 00d6097)의 커뮤니티가 관리하는 번역본입니다 — 영어 버전이 공식 버전입니다. -->

# 시작하기

## 설치

터미널에서 가장 안전한 설치 방법은 원격 부트스트랩 스크립트를 실행하는 대신 pipx로 게시된 패키지를 설치하는 것입니다.

```bash
pipx install 'maverick-agent[installer]'
maverick init
```

사전 요구 사항이 없는 데스크톱 부트스트랩이 필요하다면, 신뢰할 수 있는 커밋이나 릴리스에서 `deploy/desktop/install.sh` 또는 `deploy/desktop/install.ps1`을 내려받아 검증한 뒤 `MAVERICK_REF`에 40자 전체 커밋 SHA를 설정하세요. 이 스크립트들은 기본적으로 변경 가능한 브랜치/태그 참조를 거부합니다.

PyPI 패키지 이름은 `maverick-agent`입니다(`maverick`이라는 이름은 이미 다른 곳에서 선점했습니다). `[installer]` 엑스트라는 마법사를 커널과 같은 pipx 환경에 설치하므로 `maverick init` 명령을 찾을 수 있게 됩니다.

개발 중에 소스에서 설치하려면:

```bash
git clone https://github.com/Day-AI-Labs/maverick
cd maverick
pip install -e ./packages/maverick-core
pip install -e ./apps/installer-cli
maverick init
```

## 첫 실행

```bash
maverick init
```

마법사는 2분 정도 걸리며 `~/.maverick/config.toml`과 `~/.maverick/.env`를 기록합니다.

그다음:

```bash
maverick start "Build a CLI that emails me a digest of today's top Hacker News stories — research the API, write it, and verify it runs"
```

## 스웜이 목표를 분해하는 과정 지켜보기

두 번째 터미널에서 `maverick monitor`를 실행하세요. 오케스트레이터가 목표를 계획한 다음, 병렬로 일하는 전문 하위 에이전트들을 생성합니다. 여기서는 리서처가 API를 파악하고, 코더가 도구를 작성하며, 베리파이어가 그것을 실행해 봅니다.

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

작업이 끝나면:

```bash
maverick status      # what's currently active or blocked
maverick skills      # what the swarm distilled from this run
maverick facts       # what it learned about you
```

## 일시 중지 / 재개

스웜에 사용자만 답할 수 있는 질문이 생기면, 스웜은 일시 중지하고 질문을 대기열에 넣습니다.

```bash
maverick status
# shows: open questions: #3 (goal 1): Which dates are you traveling?

maverick answer 3 "May 15-29"
maverick resume
```

목표는 재시작 후에도 유지됩니다. 노트북을 덮고 내일 다시 돌아와도 됩니다.

## 지켜본 작업으로 나만의 전문 에이전트 만들기

작업을 말로 설명할 필요는 없습니다. 직접 보여주면 됩니다. 누군가가 그 일을 수행하는
순서대로 된 기록(그들이 취한 동작과 그 이유에 대한 설명)을 JSONL 또는 간단한 접두사가
붙은 텍스트로 캡처한 다음, 그 파일을 Lightwork에 건네주세요.

```
ACTION[gmail]: send the morning digest -> ops@acme.com
NOTE: only the top 5 stories, with one-line summaries
SEE: digest looks right, ops confirmed receipt
```

```bash
maverick learn-demo demo.txt
```

이 명령은 시연을 파싱해 초안 전문 에이전트를 유도하고, 도출된 워크플로를 보여준 뒤,
저장하기 전에 사용자의 승인을 기다립니다. 비밀 정보는 입구에서 마스킹되며, 초안은
설명으로 만든 팩과 동일한 역량 제한(capability clamp)과 페르소나 스캔을 그대로
상속받습니다. 사용자가 승인하지 않으면 아무것도 활성화되지 않습니다. 유용한 플래그:

```bash
maverick learn-demo demo.txt --name "Morning Digest" --no-llm --yes
```

`--no-llm`은 관찰된 단계를 결정론적으로 그대로 반영합니다(도구 = 사람이 실제로 사용한
것). 이 플래그를 빼면 모델이 기록을 바탕으로 제안하도록 할 수 있습니다.

대화형으로 팩을 구성할 때도 동일한 에이전트 팩토리 흐름이 실행됩니다.

```bash
maverick onboard
```

승인하면 이제 `onboard`가 팩을 프로비저닝합니다. 워크플로에 필요한 카탈로그 스킬을
설치하고, 기본 제공되지 않는 선언된 도구를 합성하므로, 갓 승인된 전문 에이전트는 첫
실행부터 자기 일을 할 수 있도록 갖춰집니다. (이 단계는 `[self_learning]` /
`provision_packs` 설정을 따르며, 팩의 제한된 범위를 결코 넓히지 않습니다.)

## 모델 또는 공급자 변경

마법사는 언제든지 다시 실행할 수 있습니다.

```bash
maverick init
```

또는 `~/.maverick/config.toml`을 직접 편집하세요. `[models]` 섹션은 각 에이전트 역할을 `provider:model-id` 문자열에 매핑합니다. 스키마는 [`configuration.md`](../../configuration.md)를 참고하세요.

## 데이터가 저장되는 위치

| 파일 | 내용 |
|---|---|
| `~/.maverick/config.toml` | 사용자 설정(배포, 모델, 안전, 예산) |
| `~/.maverick/.env` | API 키(chmod 600) |
| `~/.maverick/world.db` | 영속적인 월드 모델: 목표, 사실, 에피소드 |
| `~/.maverick/skills/` | 성공한 실행에서 자동으로 증류된 SKILL.md 파일 |
| `~/maverick-workspace/` | 샌드박스 기본 작업 디렉터리 |
| `~/.maverick/learned-skills/` | 학습 루프가 증류한 스킬 |
| `~/.maverick/dreams/` | 통합된 통찰, 리허설 큐, 학습 스냅샷 |

모든 데이터는 로컬에 있습니다. 선택한 클라우드 LLM으로 보내는 프롬프트 외에는 아무것도 업로드되지 않습니다.

실행을 몇 번 쌓고 나면, 학습 영역은 네 가지 명령으로 요약됩니다. `maverick dream`(경험
통합), `maverick hindsight`(학습이 도움이 되었는가, 아니면 퇴보했는가?),
`maverick proof`(산출물, 절감한 비용, ROI), 그리고 `maverick domains-lint`(2,020개
에이전트 전문 카탈로그 감사)이며, 여기에 `maverick domains-audit`(거버넌스 태세: 각
에이전트가 무엇에 접근하고, 무엇을 거부하며, 무엇을 거절하는지)와
`maverick domains-eval --check`(행동 골든 케이스)가 더해집니다.
