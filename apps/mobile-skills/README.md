# maverick-mobile-skills

An **honest feasibility scaffold** for running Maverick *skill logic* on
iOS/Android. Two paths, both executing the same real pure-Python module
from `maverick-core`:

| Path | What it is | Runs where |
|---|---|---|
| `pyodide-runner/` | HTML + JS page; CPython-in-WASM via a **locally vendored** Pyodide | any mobile (or desktop) browser |
| `kivy-shell/` | `main.py` Kivy app + `buildozer.spec` | Android APK / iOS via kivy-ios |

## The skill module — chosen, not hypothetical

Both paths run `packages/maverick-core/maverick/disagreement.py`
(`answer_entropy`: the proposer-disagreement signal the swarm posts to the
blackboard). It was picked by reading the candidates: **zero intra-package
imports, stdlib only** (`math`, `re`, `collections`), so it loads by file
path with no Maverick install, no pip, no native code. The test
(`test_mobile_skills.py`) imports it in isolation in a subprocess to keep
that property pinned.

## pyodide-runner

```bash
# 1. vendor Pyodide (one-time; exact URL + checksum step in
#    pyodide-runner/vendor/README.md — no CDN link is committed)
# 2. serve the REPO ROOT so the page can fetch the real module:
python -m http.server 8000
# 3. open http://localhost:8000/apps/mobile-skills/pyodide-runner/ on the phone/desktop
```

The page loads Pyodide from `./vendor/pyodide/` only, fetches
`disagreement.py` from the repo, executes it in the browser, and shows the
entropy of three sample fan-outs. Until Pyodide is vendored it shows an
instruction message instead of silently breaking.

## kivy-shell

`python kivy-shell/main.py` works three ways, most honest first:

- **No Kivy installed** (this repo's test env): prints the skill output to
  the terminal — the scaffold stays exercisable.
- **Kivy installed on desktop**: opens the app window (skill list + run
  button).
- **Packaged for Android**: `buildozer.spec` is ready; building the APK is
  a **maintainer act** on a Linux host (`pip install buildozer cython`,
  copy `disagreement.py` next to `main.py` — buildozer packages
  `source.dir` only — then `buildozer android debug`; buildozer pulls the
  Android SDK/NDK itself). **iOS** is a separate maintainer act:
  [kivy-ios] + Xcode + an Apple developer account; no `buildozer.spec`
  covers it.

[kivy-ios]: https://github.com/kivy/kivy-ios

## Hard limits — why this is skills-only, not the agent

Read this before promising "Maverick on mobile":

- **No sandbox, no subprocess.** Mobile OSes (and Pyodide's WASM runtime)
  do not allow spawning processes. Maverick's house rule is that all shell
  goes through `sandbox.exec()` — there is **no mobile backend** for it, so
  every shell-using tool is off the table. Only pure-computation skill
  logic (like this one) runs.
- **Network tools need the relay.** A phone can't host the runtime or
  receive webhooks; the supported pattern is the self-hosted relay
  (`deploy/relay/` — see its README), with the phone as a thin client.
  (There is no `docs/self-hosted-relay.md` today; `deploy/relay/README.md`
  is the relay doc.)
- **No LLM calls from the scaffold.** Provider keys on a public webpage or
  inside an APK would be exfiltratable; the scaffold deliberately ships
  zero networking (`android.permissions =` is empty).

## What was and wasn't verified here

- Verified here: the module's isolation property and sample outputs
  (subprocess import test), `main.py`'s terminal fallback, the HTML
  referencing only vendored/relative paths — `python -m pytest
  apps/mobile-skills/test_mobile_skills.py -q`.
- **Not** verified here: Pyodide actually booting (vendoring needs a
  download), the Kivy UI (no Kivy in this env), and any APK/IPA build
  (buildozer/Xcode toolchains required — maintainer acts).
