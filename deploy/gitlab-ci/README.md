# Maverick on GitLab CI

A reusable GitLab CI template that runs a Maverick agent goal in your
pipeline — the GitLab counterpart to the GitHub `agent-on-pr.yml` reusable
workflow (`deploy/github-action/`).

## Quick start

1. Add a masked CI/CD variable `ANTHROPIC_API_KEY` (Settings → CI/CD →
   Variables). To use OpenAI instead, set `OPENAI_API_KEY` and override
   `MAVERICK_MODEL`.
2. Include the template from your project's `.gitlab-ci.yml`:

   ```yaml
   include:
     - remote: 'https://raw.githubusercontent.com/cdayAI/Maverick/main/deploy/gitlab-ci/maverick.gitlab-ci.yml'
   ```

   Or vendor `maverick.gitlab-ci.yml` into your repo and use
   `include: { local: 'ci/maverick.gitlab-ci.yml' }`.

3. (Optional) Override the goal/model/budget via CI/CD variables:
   `MAVERICK_GOAL`, `MAVERICK_MODEL`, `MAVERICK_MAX_DOLLARS`.

## Safety in CI

The job sets `MAVERICK_CONSENT_MODE=auto-deny` so destructive actions are
never auto-approved and no interactive prompt can hang the pipeline, and it
configures a hard `[budget] max_dollars` cap. The default `local` sandbox
runs in the GitLab job container (`$CI_PROJECT_DIR`); use a goal scoped to
review/analysis unless you intend the agent to modify the checkout.
