# Run Lightwork in GitHub Actions

Drive a Lightwork swarm from your own CI with the composite action in
[`deploy/github-action/`](../deploy/github-action/). Hand it a goal (or a
[goal template](../benchmarks/example-templates/)) and a dollar cap; it
installs `maverick-agent`, runs `maverick start`, and writes the answer to
the job summary.

## Quickstart

```yaml
name: Ask Lightwork
on:
  workflow_dispatch:
    inputs:
      goal:
        description: "What should the swarm do?"
        required: true
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: Day-AI-Labs/maverick/deploy/github-action@v0.1.6
        with:
          goal: ${{ inputs.goal }}
          max-dollars: "0.50"
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
```

1. Add your provider key as a repo **secret** (`ANTHROPIC_API_KEY`).
2. Pin the action to a released tag (`@v0.1.6`), not `@main`.
3. Keep `max-dollars` small to start — it's a hard cap the kernel enforces.

## Common patterns

- **Review pull requests** with the `code-review` template.
- **Chain the answer** into a PR comment via the `result` output and
  `actions/github-script`.
- **Use any provider** by setting its env var on the job instead of
  `anthropic-api-key`.

Full input/output reference and copy-paste examples:
[`deploy/github-action/README.md`](../deploy/github-action/README.md).

## What's gated

The full swarm needs a provider key and spends real budget, so it does not
run in this repo's CI. The action's `dry-run: true` mode (install +
command resolution, no LLM calls) is what's smoke-tested in
[`.github/workflows/github-action.yml`](../.github/workflows/github-action.yml).

## See also

- [`benchmarks/example-templates/`](../benchmarks/example-templates/) — the
  ready-made goal templates the action can run.
- [Drive Lightwork from another language](./clients/typescript-quickstart.md)
  — the MCP client surface, for *calling* a local Lightwork from your app
  (vs. *running* one in CI here).
