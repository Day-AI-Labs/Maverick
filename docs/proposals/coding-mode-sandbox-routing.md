# Proposal (needs sign-off): route coding-mode git through `sandbox.exec()`

**Status:** NOT IMPLEMENTED — written up for your decision. Architecturally
significant (changes behavior across every sandbox backend), so per CLAUDE.md
("If a fix is ambiguous or architecturally significant, write it up and ASK")
it is deliberately left unapplied.

## The problem (launch-audit HIGH)

Coding mode's apply/validate/verify path runs `git` on the **host** via raw
`subprocess.run`, while the rest of the agent's shell goes through
`sandbox.exec()`. This violates CLAUDE.md rule 4 ("Sandbox-mediate all shell …
never call `subprocess.run` from a tool directly") and, more importantly,
**breaks coding mode for non-local sandboxes**:

- `run_failing_tests` correctly routes through the sandbox: `coding_mode.py`
  `r = sandbox.exec(c)`.
- But the FINAL handler's git ops are raw host subprocess:
  - `agent.py:220-225` — `subprocess.run(["git","-C",str(workdir),"reset","--hard","HEAD"])`
  - `agent.py:522-528`, `agent.py:702-710`, `agent.py:739-743`, `agent.py:772-780`
    — `git apply -` / diff render
  - `coding_mode.py:1702-1781` — same pattern.
- `workdir = Path(getattr(self.ctx.sandbox, "workdir", "."))`.

For `SSHBackend` the workdir is a **remote** path (`~/maverick-workspace`,
`sandbox/ssh.py`), and for `KubernetesBackend` it is an **in-pod** path
(`/workspaces/repo`, `sandbox/kubernetes.py`). So `git -C <that-path> apply` on
the host operates on a path that **doesn't exist locally / is a different tree**
than where the agent's edits and tests actually ran. Docker/podman work only by
the bind-mount accident (`docker.py` mounts the host workdir to `/workspace`).

Net: coding mode silently produces wrong/empty patches under SSH/k8s/firecracker.

## Proposed fix

Route every git operation in the coding-mode apply/validate/verify path through
`self.ctx.sandbox.exec(...)` instead of `subprocess.run`, so they execute in the
same filesystem context as the edits and tests.

- `git reset --hard HEAD`, `git diff`, `git apply --check`, `git apply` →
  `sandbox.exec("git -C <workdir> …")` (the sandbox already cd's/wraps per
  backend).
- `git apply -` reads the patch from **stdin**, which `sandbox.exec()` may not
  support uniformly across backends. Two options:
  1. Write the patch to a temp file **inside the sandbox** (`sandbox.exec` a
     heredoc / `write_file` tool) and `git apply <tmpfile>`; or
  2. Add an optional `stdin=` parameter to the `sandbox.Backend.exec`
     contract and implement it per backend (local: `subprocess` stdin; ssh:
     pipe over the ssh channel; docker: `docker exec -i`).
  Option 1 is lower-risk (no contract change); Option 2 is cleaner long-term.

## Why this needs your sign-off (risks)

- **Touches every sandbox backend's contract/behavior.** A regression here breaks
  coding mode (the SWE-bench path) for *all* users, not just remote ones.
- The `git apply -` stdin handling is the crux; getting it wrong silently drops
  patches (exactly the failure class we're fixing).
- It is **not** a launch blocker for the default (`local`) sandbox — local
  coding mode works today. The bug bites SSH/k8s/firecracker users, who are a
  later-quarter audience.

## Verification plan (before merge)

1. Unit: a fake sandbox recording `exec()` calls — assert the FINAL handler
   issues git via `sandbox.exec`, never `subprocess`.
2. Integration (local backend): the existing
   `test_integration_swe_smoke::test_full_pipeline_produces_valid_patch` must
   still pass (note: it is **currently failing on main**, unrelated — investigate
   that first so it's a real gate).
3. SSH/k8s: exercise against a configured remote/cluster (not available in the
   audit environment) — confirm the patch is rendered from the remote tree.

## Recommendation

Schedule as a fast-follow right after launch (it's a real correctness bug for
remote sandboxes and a clean CLAUDE.md-rule-4 fix), but do **not** rush it into
the v0.1.3 tag — the default local sandbox is unaffected and the change is wide.
