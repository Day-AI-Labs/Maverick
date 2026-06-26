#!/usr/bin/env bash
# Run the full CI "lint" job locally before pushing.
#
# Plain `ruff`/`pytest` miss the bespoke gates that have repeatedly failed CI
# *after* a green local run: the detect-secrets baseline check (which only scans
# git-TRACKED files), the `shell=True` source grep, the plugin/deprecation/proto/
# a11y/schema gates. This mirrors the lint job in .github/workflows/ci.yml so
# those surface here instead of on CI.
#
# Usage:  bash scripts/pre-push-lint.sh
# Tip:    `git add -A` first — the secret scan only sees tracked files.
#
# Exits non-zero if any gate fails; runs them all so you see every failure at once.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

fail=0
run() {  # run "<name>" <command...>
  local name="$1"; shift
  if "$@" >/tmp/ppl.out 2>&1; then
    printf '  ok   %s\n' "$name"
  else
    printf '  FAIL %s\n' "$name"; sed 's/^/       /' /tmp/ppl.out | tail -20
    fail=1
  fi
}

echo "== ruff =="
run "ruff check ." python -m ruff check .

echo "== vulture (dead code) =="
run "vulture" python -m vulture

echo "== bare 'import tomllib' (needs the 3.10 tomli fallback) =="
if grep -rn --include='*.py' -E '^import[[:space:]]+tomllib([[:space:]]|$)' apps packages benchmarks; then
  echo "  FAIL bare 'import tomllib' (use the try/except tomli fallback)"; fail=1
else
  echo "  ok   no bare tomllib"
fi

echo "== shell=True confined to maverick/sandbox/ =="
hits="$(grep -rn --include='*.py' 'shell=True' apps packages | grep -v '/sandbox/' | grep -v '/tests/' || true)"
if [ -n "$hits" ]; then
  echo "  FAIL shell=True outside sandbox/ (also catches the literal in comments):"; echo "$hits" | sed 's/^/       /'; fail=1
else
  echo "  ok   no stray shell=True"
fi

echo "== detect-secrets vs audited baseline (TRACKED files only) =="
if command -v detect-secrets >/dev/null 2>&1; then
  cp .secrets.baseline /tmp/scan.baseline
  detect-secrets scan --baseline /tmp/scan.baseline >/dev/null 2>&1
  if python3 - <<'PY'
import json, sys
old = json.load(open(".secrets.baseline"))["results"]
new = json.load(open("/tmp/scan.baseline"))["results"]
pairs = lambda r: {(f, i["hashed_secret"]) for f, items in r.items() for i in items}
extra = sorted(pairs(new) - pairs(old))
if extra:
    print("new secret(s) not in .secrets.baseline:")
    for f, h in extra:
        print(f"  {f}  (sha1 {h[:16]}...)")
    sys.exit(1)
PY
  then echo "  ok   no new secrets"; else echo "  FAIL new secret(s) — add '# pragma: allowlist secret' or re-audit the baseline"; fail=1; fi
else
  echo "  skip detect-secrets not installed (pip install 'detect-secrets>=1.5')"
fi

echo "== custom CI gates =="
run "plugin_matrix --ci"      python -m maverick.plugin_matrix --ci
run "deprecations --ci"       python -m maverick.deprecations --ci
run "grpc contract --check"   python -m maverick.grpc_api.contract --check
run "a11y_audit --ci"         python -m maverick.a11y_audit --ci
run "schema_migrations --ci"  python -m maverick.schema_migrations --ci

echo
if [ "$fail" -ne 0 ]; then
  echo "FAILED — fix the gates above before pushing."; exit 1
fi
echo "All lint gates passed. (The security job — pip-audit/bandit/SBOM — runs separately in CI.)"
