"""Pre-run contamination check (mandatory post-Feb-2026 audit).

OpenAI's Feb 2026 audit of SWE-bench Verified found 59.4% of failed
tasks had flawed tests, AND that several frontier models showed
verbatim leakage of the gold patch in their training data. After that
admission, the community standard is to RUN this guard before
publishing any benchmark number.

What we check:
- The brief / prompt doesn't appear verbatim in the model's recent
  training data (heuristic: known leaked-corpus hashes).
- The predicted_patch doesn't byte-equal the gold patch (suggests
  retrieval / memorization rather than reasoning).
- The model_id wasn't trained on data after the benchmark's
  publication cutoff (best-effort: based on a hard-coded lookup
  table that we update as new models ship).

The guard is forgiving by design: it returns a list of FLAGS rather
than blocking the run. Headline numbers that have any flag must be
reported with a caveat or excluded.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass
class ContaminationFlag:
    severity: str   # "high" | "medium" | "low"
    kind: str
    reason: str


# Model -> training-cutoff (ISO date). Best-effort, update on each
# new model release. Source: model card / provider announcement.
MODEL_CUTOFFS: dict[str, str] = {
    "claude-opus-4-7":      "2025-12-01",
    "claude-sonnet-4-6":    "2025-08-01",
    "claude-haiku-4-5":     "2025-08-01",
    "gpt-5.5":              "2026-02-01",
    "gpt-5.4":              "2025-11-01",
    "gpt-5.4-pro":          "2025-11-01",
    "gemini-3-pro":         "2025-10-01",
    "deepseek-v4-pro":      "2025-12-01",
    "grok-4.3":             "2026-03-01",
    "qwen3-32b":            "2025-09-01",
}


def check(
    *,
    task_id: str,
    brief: str,
    predicted_patch: str,
    gold_patch: str = "",
    model_id: str = "",
    benchmark_publication_date: str = "",
) -> list[ContaminationFlag]:
    flags: list[ContaminationFlag] = []

    # Cutoff vs publication.
    cutoff = MODEL_CUTOFFS.get(model_id, "") or MODEL_CUTOFFS.get(
        model_id.split(":", 1)[-1], "",
    )
    if cutoff and benchmark_publication_date:
        if cutoff > benchmark_publication_date:
            flags.append(ContaminationFlag(
                severity="high",
                kind="post_publication_cutoff",
                reason=(
                    f"Model {model_id} training cutoff {cutoff} is after "
                    f"benchmark publication {benchmark_publication_date} -- "
                    "possible exposure to gold answers during training."
                ),
            ))

    # Verbatim leakage: the model emitted the gold patch byte-for-byte.
    # SWE-bench Verified's Feb 2026 audit showed this happened for some
    # frontier models on tasks where the gold patch was in a popular
    # GitHub repo crawled into training data.
    if gold_patch and predicted_patch and predicted_patch.strip() == gold_patch.strip():
        flags.append(ContaminationFlag(
            severity="high",
            kind="verbatim_gold_patch",
            reason=(
                "Predicted patch is byte-identical to the gold patch. "
                "Probable memorization / retrieval rather than reasoning."
            ),
        ))

    # Brief in known-leaked corpus. The actual corpus check requires a
    # bloom filter / lookup we ship separately; here we hash the brief
    # and compare against a small built-in list of confirmed-leaked
    # SWE-bench Verified instance briefs (placeholder; expand as the
    # community surfaces more).
    if brief:
        h = hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]
        if h in _KNOWN_LEAKED_BRIEFS:
            flags.append(ContaminationFlag(
                severity="medium",
                kind="brief_in_leaked_corpus",
                reason=(
                    f"Brief hash {h} is in the known-leaked-corpus list "
                    "(community-maintained). Treat results as suspect."
                ),
            ))

    return flags


# Community-maintained set of brief hashes known to leak into training
# data (e.g. found in GitHub issues / PRs that pre-date the benchmark
# split). Add IDs as you find them; this is intentionally short until
# we have a real lookup service.
_KNOWN_LEAKED_BRIEFS: set[str] = set()


def add_known_leaked_brief(brief: str) -> None:
    """Allow harness code or operators to extend the leaked-brief set."""
    h = hashlib.sha256(brief.strip().encode("utf-8")).hexdigest()[:16]
    _KNOWN_LEAKED_BRIEFS.add(h)
