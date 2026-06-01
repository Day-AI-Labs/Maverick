"""Pre-flight checks for SWE-bench Pro / Verified benchmark runs.

Catches the most common failure modes BEFORE you burn money:

  - ANTHROPIC_API_KEY is set + actually works (cheap test ping)
  - Model IDs you're about to run on are valid May-2026 names
  - ~/.maverick/config.toml doesn't silently override your env vars
  - Enough disk space for Docker images (~200GB for Pro)
  - Required hosts (Anthropic / HuggingFace / Docker Hub) are reachable
  - Wave 11 env vars are set sensibly

Usage::

    python benchmarks/preflight.py
    python benchmarks/preflight.py --skip-network    # offline mode
    python benchmarks/preflight.py --min-disk-gb 50  # smaller threshold

Exits 0 on PASS, 2 on FAIL. Each failure prints a single-line
explanation + the env var / config field you need to fix. Friendly
for operator use, not just CI; everything important is colored.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
from pathlib import Path


# ANSI colors that no-op on Windows older terminals (colorama not used
# because we don't want a new dep just for this script).
_RED = "\033[31m" if sys.stdout.isatty() else ""
_GREEN = "\033[32m" if sys.stdout.isatty() else ""
_YELLOW = "\033[33m" if sys.stdout.isatty() else ""
_RESET = "\033[0m" if sys.stdout.isatty() else ""


def _ok(msg: str) -> None:
    print(f"{_GREEN}PASS{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"{_YELLOW}WARN{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"{_RED}FAIL{_RESET}  {msg}")


def check_api_key() -> bool:
    """ANTHROPIC_API_KEY set + actually pings successfully."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        _fail(
            "ANTHROPIC_API_KEY not set. "
            "PowerShell: $env:ANTHROPIC_API_KEY = 'sk-ant-...'. "
            "bash: export ANTHROPIC_API_KEY=sk-ant-..."
        )
        return False
    if not key.startswith(("sk-ant-", "sk-")):
        _warn(f"ANTHROPIC_API_KEY does not start with `sk-ant-` (length={len(key)})")
    try:
        import anthropic
    except ImportError:
        _fail("anthropic package not installed. Run: pip install anthropic")
        return False
    try:
        client = anthropic.Anthropic(api_key=key)
        # Cheapest possible call: 1-token completion on Haiku.
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "."}],
        )
        if not resp.id:
            _fail("Anthropic API returned an empty response. Investigate.")
            return False
    except anthropic.AuthenticationError:
        _fail(
            "Anthropic API rejected the key (401). Check ANTHROPIC_API_KEY "
            "matches an active key in console.anthropic.com."
        )
        return False
    except anthropic.PermissionDeniedError as e:
        _fail(f"Anthropic API key lacks permission: {e}")
        return False
    except anthropic.NotFoundError:
        # Model name might be wrong (Haiku 4.5 unavailable in this org's tier).
        _warn(
            "claude-haiku-4-5 not accessible to this API key. "
            "Falling back to a generic model check..."
        )
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1,
                messages=[{"role": "user", "content": "."}],
            )
        except Exception as e:
            _fail(f"Fallback model check also failed: {e}")
            return False
    except Exception as e:
        _fail(f"Anthropic API ping failed: {type(e).__name__}: {e}")
        return False
    _ok("ANTHROPIC_API_KEY valid; API ping succeeded")
    return True


def check_model_ids() -> bool:
    """Confirm the models the agent will route to are recognised May-2026
    identifiers. We just check the env-var overrides + ROLE_MODELS table
    are consistent with the price table; mis-spelled model IDs would
    cause every API call to 404."""
    try:
        from maverick.llm import MODEL_PRICES, ROLE_MODELS
    except ImportError:
        _fail("Cannot import maverick.llm — did you run `pip install -e ./packages/maverick-core`?")
        return False
    role_specific_envs = {
        role: os.environ.get(f"MAVERICK_MODEL_OVERRIDE_{role.upper()}")
        for role in ROLE_MODELS
    }
    bad = []
    for role, model in ROLE_MODELS.items():
        override = role_specific_envs.get(role)
        resolved = override or model
        # provider:model-id form -- strip the provider for the table.
        bare = resolved.split(":", 1)[-1]
        if bare not in MODEL_PRICES:
            bad.append((role, resolved))
    if bad:
        for role, m in bad:
            _fail(
                f"role={role} resolves to model {m!r} which is not in "
                "MODEL_PRICES. Check spelling against maverick/llm.py."
            )
        return False
    # Check the BoN ladder too.
    ladder_str = os.environ.get(
        "MAVERICK_BON_LADDER",
        "claude-sonnet-4-6:0.3,claude-sonnet-4-6:0.7,claude-opus-4-7:0.4",
    )
    for entry in ladder_str.split(","):
        if ":" not in entry:
            continue
        model_id, _ = entry.rsplit(":", 1)
        if model_id.strip() and model_id.strip() not in MODEL_PRICES:
            _fail(
                f"MAVERICK_BON_LADDER references unknown model "
                f"{model_id.strip()!r}; not in MODEL_PRICES."
            )
            return False
    _ok(f"All role model IDs known ({len(ROLE_MODELS)} roles + BoN ladder)")
    return True


def check_config_no_stale_overrides() -> bool:
    """A stale ~/.maverick/config.toml could override our env vars and
    silently route to the wrong model. Warn loudly if so."""
    cfg_path = Path.home() / ".maverick" / "config.toml"
    if not cfg_path.exists():
        _ok("no ~/.maverick/config.toml; using env vars + defaults")
        return True
    try:
        if sys.version_info >= (3, 11):
            import tomllib
            cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
        else:
            import tomli
            cfg = tomli.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        _warn(f"~/.maverick/config.toml exists but failed to parse: {e}")
        return True  # Don't block; parse failure means it won't be used.
    models = cfg.get("models", {})
    coding_mode = os.environ.get("MAVERICK_CODING_MODE", "").lower() in ("1", "true")
    has_override = bool(models)
    if has_override and coding_mode:
        _warn(
            f"~/.maverick/config.toml has [models] section with overrides "
            f"{list(models.keys())}. These WILL override Wave 11 env vars "
            f"(MAVERICK_MODEL_OVERRIDE_<ROLE>) unless cleared. Either "
            f"delete the [models] section for the bench run, OR set the "
            f"per-role env vars explicitly."
        )
    else:
        _ok(f"config.toml present, no conflicts ({len(models)} model overrides)")
    return True


def check_disk_space(min_gb: float) -> bool:
    """Need ≥200GB free for the full SWE-bench Pro Docker image set
    (~150GB pull + headroom for trace JSONL + result CSVs)."""
    home = Path.home()
    try:
        usage = shutil.disk_usage(home)
    except OSError as e:
        _fail(f"could not check disk usage on {home}: {e}")
        return False
    free_gb = usage.free / (1024 ** 3)
    if free_gb < min_gb:
        _fail(
            f"only {free_gb:.1f}GB free on {home.anchor or home} "
            f"(need ≥{min_gb}GB for SWE-bench Pro Docker images + traces). "
            f"Free up space or change MAVERICK_TRACE_DIR / Docker root to "
            f"a larger volume."
        )
        return False
    _ok(f"{free_gb:.1f}GB free on {home.anchor or home} (≥{min_gb}GB required)")
    return True


def check_network_egress() -> bool:
    """The benchmark needs to reach Anthropic (LLM calls), HuggingFace
    (dataset download), and Docker Hub (image pulls for grader). A
    hostile firewall would silently 0-resolve some of these."""
    hosts = [
        ("api.anthropic.com", 443),
        ("huggingface.co", 443),
        ("docker.io", 443),
        ("auth.docker.io", 443),  # Docker Hub authentication
    ]
    failed: list[str] = []
    for host, port in hosts:
        try:
            with socket.create_connection((host, port), timeout=5):
                pass
        except (socket.gaierror, OSError) as e:
            failed.append(f"{host}:{port} ({e})")
    if failed:
        _fail("unreachable hosts: " + ", ".join(failed))
        return False
    _ok(f"network egress OK to {len(hosts)} required hosts")
    return True


def check_wave11_env() -> bool:
    """Soft sanity-check on the Wave 11 env-var matrix. Warnings only —
    we don't refuse to run if any are missing, just surface anomalies."""
    expected = {
        "MAVERICK_CODING_MODE": "1",
        "MAVERICK_BENCHMARK_OPAQUE": "1",
        "MAVERICK_USE_SKILLS": "0",
        "MAVERICK_MAX_STEPS": "25",
    }
    for k, v in expected.items():
        actual = os.environ.get(k)
        if actual is None:
            _warn(f"{k} not set (Wave 11 runbook recommends {k}={v!r})")
        elif actual != v:
            _warn(f"{k}={actual!r} (Wave 11 runbook recommends {k}={v!r})")
    bon = os.environ.get("MAVERICK_BEST_OF_N")
    if bon:
        try:
            bon_int = int(bon)
        except ValueError:
            _warn(
                f"MAVERICK_BEST_OF_N={bon!r} is not an integer; ignoring this "
                "warning-only advisory."
            )
        else:
            if bon_int > 4:
                _warn(
                    f"MAVERICK_BEST_OF_N={bon} is unusually high (research consensus is "
                    "N=3 heterogeneous; N>4 sees diminishing returns and cost blowup)."
                )
    instance_cap = os.environ.get("MAVERICK_INSTANCE_HARD_CAP")
    if not instance_cap:
        _warn(
            "MAVERICK_INSTANCE_HARD_CAP not set (recommended: 3.0). Without "
            "this, a runaway instance could eat the entire run budget."
        )
    _ok("Wave 11 env var check complete (see warnings above, if any)")
    return True


def check_python_version() -> bool:
    """Maverick targets 3.10+. 3.13 isn't officially tested but works."""
    if sys.version_info < (3, 10):
        _fail(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is "
            "below the supported minimum (3.10). Upgrade Python."
        )
        return False
    if sys.version_info >= (3, 13):
        _warn(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is "
            "newer than CI's tested range (3.10-3.12). Works but unsupported."
        )
    else:
        _ok(f"Python {sys.version_info.major}.{sys.version_info.minor} (supported)")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-network", action="store_true",
                    help="Skip network egress checks (for offline boxes).")
    ap.add_argument("--skip-api", action="store_true",
                    help="Skip the Anthropic API ping (free, but ~1 second).")
    ap.add_argument("--min-disk-gb", type=float, default=200.0,
                    help="Minimum free GB required (default 200; Verified-only "
                    "can use 50).")
    args = ap.parse_args()

    print("Running pre-flight checks for SWE-bench Pro / Verified...\n")
    all_pass = True

    if not check_python_version():
        all_pass = False
    if not args.skip_api and not check_api_key():
        all_pass = False
    if not check_model_ids():
        all_pass = False
    check_config_no_stale_overrides()  # warning only
    if not check_disk_space(args.min_disk_gb):
        all_pass = False
    if not args.skip_network and not check_network_egress():
        all_pass = False
    check_wave11_env()  # warning only

    print()
    if all_pass:
        print(f"{_GREEN}All required checks passed.{_RESET}")
        print("You can proceed with the shadow benchmark per the runbook.")
        return 0
    print(f"{_RED}One or more required checks failed.{_RESET}")
    print("Fix the failures above before launching a paid run.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
