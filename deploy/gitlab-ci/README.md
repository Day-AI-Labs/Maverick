# Maverick GitLab CI template

Run a Maverick agent goal inside a GitLab pipeline — on a merge request, on
a schedule, or on demand — under a **hard spend cap** and with
non-interactive safety defaults. The reusable
[`maverick.gitlab-ci.yml`](./maverick.gitlab-ci.yml) template installs
`maverick-agent` from PyPI and runs `maverick start "$MAVERICK_GOAL"`.

It is the GitLab counterpart to the [`deploy/github-action`](../github-action)
wrapper and mirrors the same safety inputs: consent mode, budget cap, and
sandbox scope.

## Usage

In your project's `.gitlab-ci.yml`, `include:` the template and define a job
that `extends` the hidden `.maverick` job:

```yaml
include:
  - remote: 'https://gitlab.com/cdayAI/maverick/-/raw/main/deploy/gitlab-ci/maverick.gitlab-ci.yml'

maverick:
  extends: .maverick
  variables:
    MAVERICK_GOAL: "Review the changes on this branch and flag any risks."
    MAVERICK_MAX_DOLLARS: "0.50"
```

> Pin to a tag or commit (`/-/raw/v0.1.6/...`) rather than `main` so a
> template you didn't write can't change under you.

## Required CI/CD variables

Set these under **Settings → CI/CD → Variables** (mark the API key as
*Masked* and *Protected*):

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Provider key, written into the generated config. For another provider, leave it blank and set that provider's env var on the job. |
| `MAVERICK_GOAL` | yes | The goal text passed to `maverick start`. The job fails fast if it is empty. |
| `MAVERICK_MAX_DOLLARS` | no (default `1.0`) | Hard USD spend cap, wired into `[budget] max_dollars`. The kernel refuses to exceed it. |
| `MAVERICK_MODEL` | no | Model override, e.g. `anthropic:claude-sonnet-4-6` (passed as `maverick --model`). |
| `MAVERICK_VERSION` | no (latest) | `maverick-agent` version to install. **Pin it** for reproducible runs. |
| `MAVERICK_PYTHON_VERSION` | no (default `3.12`) | Python image tag used for the job. |

## Safety defaults

These are baked into the template so a pipeline run is safe by default:

- **`MAVERICK_CONSENT_MODE: auto-deny`** — a pipeline has no human at a
  prompt, so any tool call that would ask for consent is denied rather than
  hanging the job.
- **Hard budget cap** — `MAVERICK_MAX_DOLLARS` is written to
  `[budget] max_dollars` and passed as `--max-dollars`. A runaway goal stops
  instead of running up a bill. Start small.
- **Sandbox scoped to the checkout** — the `local` sandbox's `workdir` is
  set to `$CI_PROJECT_DIR`, so model-generated shell operates on the cloned
  project, not the whole runner.

## Notes

- **Keys are secrets.** Pass `ANTHROPIC_API_KEY` as a masked CI/CD variable,
  never inline in `.gitlab-ci.yml`.
- The full run needs a provider key, so it isn't exercised in this repo's
  CI; a structural test (`test_gitlab_ci_template.py`) checks the template
  parses and the safety defaults are present.
