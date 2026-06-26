"""Repo-root pytest bootstrap: isolate ``~/.maverick`` BEFORE any maverick import.

Many maverick modules freeze ``Path.home()``-derived paths into module-level
constants at import time (``world_model.DEFAULT_DB``, ``skills.SKILLS_DIR``,
``skill_stats.DEFAULT_PATH``, ``self_learning.LEARNED_PATH``, the audit dirs,
...). The per-test ``HOME`` monkeypatch in maverick-core's conftest runs too
late for those: in a full-suite run the first collected module to import
maverick bakes the REAL home into the constants, and every test that then
relies on a default path writes the developer's actual ``~/.maverick`` --
observed as fake swe-bench goals + phantom spend in ``maverick budget``, junk
``good``/``bad`` skills that ``relevant_skills()`` would inject into REAL
future runs, and test rows in the real audit log.

Mutating the environment at root-conftest *import* is the earliest hook pytest
offers: it precedes package conftests and every collection import, so the
frozen constants bake a throwaway session dir instead. It also covers
``benchmarks/`` (no conftest of its own) and ``apps/``. Per-test ``tmp_path``
HOME fixtures still apply on top for call-time resolution, and subprocesses
spawned by tests inherit the redirect.

``test_home_isolation.py`` pins this contract against the OS-level home (via
``pwd``), which environment variables cannot fool.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_session_home = tempfile.mkdtemp(prefix="maverick-test-home-")
os.environ["HOME"] = _session_home
os.environ["USERPROFILE"] = _session_home  # Windows: what Path.home() reads
atexit.register(shutil.rmtree, _session_home, True)

# Secure-by-default ships ON in production (audit signing, at-rest encryption,
# fail-closed high-risk consent, ...). The existing suite asserts each control's
# on/off mechanics under explicit config, so pin the legacy posture here for
# stability (same pattern as the MAVERICK_BUILTIN_SKILLS=0 pin); the secure
# DEFAULT itself is covered by test_secure_defaults.py, which overrides this.
os.environ.setdefault("MAVERICK_SECURE_DEFAULT", "0")
