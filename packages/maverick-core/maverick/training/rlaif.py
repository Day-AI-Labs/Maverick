"""RLAIF / DPO loop on the proposer using verifier rewards as the signal.

This is the third stage of the training flywheel (after ``ingest`` and
``prm_train``). The idea, in one line: the *verifier* is the AI feedback
in "RL from AI Feedback" — instead of asking a human which of two
proposer attempts is better, we ask "which attempt did the verifier
reward more?" and use that as the DPO preference label.

Pipeline
--------
1. ``ingest`` writes Klear-format JSONL (one row per trajectory) with a
   ``terminal_reward`` (the verifier's final score) and a
   ``meta.verifier_confidence``.
2. This module groups trajectories by ``task_family`` and, within a
   group, pairs a higher-reward attempt (``chosen``) against a
   lower-reward attempt (``rejected``) whenever the reward gap is wide
   enough to be a trustworthy preference signal.
3. Those pairs feed a textbook DPO objective that nudges the proposer
   toward the ``chosen`` continuations and away from the ``rejected``
   ones.

Operator usage::

    python -m maverick.training.rlaif \\
        --data trajectories.jsonl \\
        --base-model <hf-id-or-path> \\
        --out ./proposer_dpo \\
        [--beta 0.1 --epochs 1 --lr 5e-7 --min-margin 0.5 --max-pairs 32]

Honest limitations
------------------
* The pure pair-construction (``load_klear`` / ``build_preference_pairs``)
  is unit-tested and has no heavy dependencies.
* The actual ``train`` loop LAZILY imports ``torch`` + ``transformers``
  and requires a GPU plus a real base model. It is NOT exercised by the
  test suite — see ``train``'s docstring.
* Klear rows do NOT carry the raw proposer text (the ``messages`` array
  is hashed/structural to avoid leaking PII). Real DPO needs the actual
  prompt/response token strings, which live operator-side. Here we
  reconstruct a *structural* sequence string from message
  ``role``/``type``/``name`` as a documented stand-in — see
  ``trajectory_to_text``.

The kernel never imports this module's heavy deps; ``torch`` /
``transformers`` are optional and only touched inside ``train``.
"""
from __future__ import annotations

import argparse
import json
import sys
from heapq import heappop, heappush
from pathlib import Path

# ---------------------------------------------------------------------------
# Pure, unit-testable helpers (no torch / transformers).
# ---------------------------------------------------------------------------


def load_klear(path: str | Path) -> list[dict]:
    """Read a Klear-format JSONL file (one trajectory per line).

    Blank lines and lines that fail to parse as JSON are skipped so a
    truncated final write doesn't abort a long training run.
    """
    rows: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def trajectory_to_text(row: dict) -> str:
    """Reconstruct a structural sequence string for a trajectory row.

    LIMITATION (read this before trusting the output): Klear rows store
    ``messages`` as a *hashed/structural* summary (role + action type +
    tool name + observation hash) precisely so raw observations never
    enter the training corpus. Real DPO needs the actual proposer
    prompt/response *text*, which is operator-side data not present here.

    As a documented stand-in we join the structural fields into a single
    line per message, e.g. ``planner/think | observer/tool_call:grep``.
    This is enough to (a) keep chosen/rejected attempts distinguishable
    and (b) wire the DPO plumbing end-to-end, but an operator running
    real RLAIF MUST replace this with the raw text join from their own
    proposer logs.
    """
    parts: list[str] = []
    for m in row.get("messages", []) or []:
        role = m.get("role", "") or ""
        atype = m.get("type", "") or ""
        name = m.get("name", "") or ""
        token = f"{role}/{atype}"
        if name:
            token += f":{name}"
        if m.get("error"):
            token += "!err"
        parts.append(token)
    return " | ".join(parts)


def build_preference_pairs(
    rows: list[dict],
    *,
    min_margin: float = 0.5,
    max_pairs_per_group: int = 32,
) -> list[dict]:
    """Build DPO (chosen, rejected) preference pairs from verifier rewards.

    The verifier's ``terminal_reward`` IS the AI feedback: within a
    ``task_family`` group, any attempt that out-scored another by at
    least ``min_margin`` becomes a (chosen, rejected) pair. Pairing only
    happens *within* a family so we never compare apples (a SWE task) to
    oranges (a research task).

    Args:
        rows: Klear-format trajectory dicts (see ``load_klear``).
        min_margin: Minimum ``terminal_reward`` gap for a pair to count.
            Gaps below this are treated as noise and dropped.
        max_pairs_per_group: Cap on pairs emitted per ``task_family`` to
            avoid the O(n^2) blowup of all-vs-all pairing. We keep the
            ``max_pairs_per_group`` widest-margin pairs (largest, most
            confident preferences first).

    Verifier confidence handling:
        ``meta.verifier_confidence`` is folded into each pair as a
        ``weight`` = mean of the two attempts' confidences (in [0, 1],
        defaulting to 1.0 when absent). It is ALSO the tie-breaker for
        the per-group cap: among pairs with equal reward margin, the
        higher-confidence pair is kept. A DPO trainer can multiply each
        pair's loss by ``weight`` so low-confidence verifier judgements
        contribute proportionally less.

    Returns:
        A list of dicts, each::

            {
              "task_family", "chosen_id", "rejected_id",
              "chosen_reward", "rejected_reward", "margin", "weight",
            }

        sorted by descending ``margin`` then descending ``weight``.
    """
    # Group by task_family, skipping rows with a missing/empty family.
    groups: dict[str, list[dict]] = {}
    for r in rows:
        fam = r.get("task_family")
        if not fam:  # None or "" -> can't trust cross-family comparisons.
            continue
        groups.setdefault(fam, []).append(r)

    if max_pairs_per_group <= 0:
        return []

    pairs: list[dict] = []
    for fam, members in groups.items():
        if len(members) < 2:
            continue

        # Sort once by reward so each high-reward row can be paired with
        # progressively lower-reward rows.  A max-heap over those per-row
        # streams lets us keep only the configured cap instead of building
        # and sorting every all-vs-all candidate for large task families.
        ranked = sorted(
            ((_reward(member), member) for member in members),
            key=lambda item: (-item[0], _confidence(item[1])),
        )
        heap: list[tuple[float, float, int, int]] = []
        last = len(ranked) - 1
        for i, (high_reward, high) in enumerate(ranked[:-1]):
            low_reward, low = ranked[last]
            margin = high_reward - low_reward
            if margin < min_margin:
                continue
            weight = (_confidence(high) + _confidence(low)) / 2.0
            heappush(heap, (-margin, -weight, i, last))

        group_pairs: list[dict] = []
        while heap and len(group_pairs) < max_pairs_per_group:
            _neg_margin, _neg_weight, i, j = heappop(heap)
            high_reward, high = ranked[i]
            low_reward, low = ranked[j]
            group_pairs.append(_preference_pair(fam, high, low, high_reward, low_reward))

            next_j = j - 1
            if next_j <= i:
                continue
            next_low_reward, next_low = ranked[next_j]
            next_margin = high_reward - next_low_reward
            if next_margin < min_margin:
                continue
            next_weight = (_confidence(high) + _confidence(next_low)) / 2.0
            heappush(heap, (-next_margin, -next_weight, i, next_j))

        pairs.extend(group_pairs)

    pairs.sort(key=lambda p: (p["margin"], p["weight"]), reverse=True)
    return pairs


def _reward(row: dict) -> float:
    """Terminal reward for sorting and margin calculations."""
    return float(row.get("terminal_reward", 0.0) or 0.0)


def _preference_pair(
    fam: str,
    chosen: dict,
    rejected: dict,
    chosen_reward: float,
    rejected_reward: float,
) -> dict:
    """Create one verifier-reward preference pair."""
    conf_c = _confidence(chosen)
    conf_r = _confidence(rejected)
    return {
        "task_family": fam,
        "chosen_id": chosen.get("id"),
        "rejected_id": rejected.get("id"),
        "chosen_reward": chosen_reward,
        "rejected_reward": rejected_reward,
        "margin": chosen_reward - rejected_reward,
        "weight": (conf_c + conf_r) / 2.0,
    }


def _confidence(row: dict) -> float:
    """Verifier confidence for a row, clamped to [0, 1], default 1.0."""
    meta = row.get("meta") or {}
    try:
        c = float(meta.get("verifier_confidence", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return max(0.0, min(1.0, c))


# ---------------------------------------------------------------------------
# DPO training loop (heavy deps lazily imported; GPU + real model required).
# ---------------------------------------------------------------------------


def train(
    pairs: list[dict],
    base_model: str,
    out_dir: str | Path,
    *,
    rows_by_id: dict[str, dict] | None = None,
    beta: float = 0.1,
    epochs: int = 1,
    lr: float = 5e-7,
) -> int:
    """Run a minimal, textbook DPO loop over the preference pairs.

    REQUIRES a GPU and a real causal-LM ``base_model`` (HF id or path).
    This function is NOT covered by the unit tests — only the missing-dep
    path is. ``torch`` and ``transformers`` are imported lazily here so
    the kernel never depends on them.

    DPO objective (Rafailov et al., arxiv:2305.18290), per pair::

        L = -log sigmoid( beta * (
                (logp_pi(chosen)  - logp_ref(chosen))
              - (logp_pi(rejected) - logp_ref(rejected)) ) )

    where ``pi`` is the model being trained and ``ref`` is a frozen copy
    of the base model. ``beta`` is the KL temperature. Each pair's loss
    is scaled by its verifier-confidence ``weight``.

    Args:
        pairs: Output of ``build_preference_pairs``.
        base_model: HF model id or local path for both policy and ref.
        out_dir: Directory to save the fine-tuned proposer.
        rows_by_id: Mapping of trajectory id -> Klear row, used to
            recover the (structural stand-in) text for each attempt. If
            None, ``pairs`` must already carry ``chosen_text`` /
            ``rejected_text`` keys.
        beta, epochs, lr: Standard DPO hyperparameters.

    Returns:
        0 on success, 1 if the heavy deps are missing.
    """
    try:
        import torch
        import torch.nn.functional as F
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print(
            "RLAIF/DPO training needs torch + transformers, which are "
            "optional. Install them with:\n"
            "    pip install 'maverick-agent[training]'",
            file=sys.stderr,
        )
        return 1

    if not pairs:
        print("no preference pairs to train on; nothing to do.", file=sys.stderr)
        return 0

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    policy = AutoModelForCausalLM.from_pretrained(base_model).to(device)
    ref = AutoModelForCausalLM.from_pretrained(base_model).to(device)
    ref.eval()
    for p in ref.parameters():
        p.requires_grad_(False)

    opt = torch.optim.AdamW(policy.parameters(), lr=lr)

    def seq_logp(model, text: str):
        """Sum of token log-probs of ``text`` under ``model``."""
        ids = tokenizer(text, return_tensors="pt").input_ids.to(device)
        logits = model(ids).logits[:, :-1, :]
        targets = ids[:, 1:]
        logp = F.log_softmax(logits, dim=-1)
        token_logp = logp.gather(-1, targets.unsqueeze(-1)).squeeze(-1)
        return token_logp.sum()

    def text_for(pair: dict, key: str) -> str:
        if f"{key}_text" in pair:
            return pair[f"{key}_text"]
        assert rows_by_id is not None, "rows_by_id required to recover text"
        return trajectory_to_text(rows_by_id[pair[f"{key}_id"]])

    policy.train()
    for epoch in range(epochs):
        total = 0.0
        for pair in pairs:
            chosen_text = text_for(pair, "chosen")
            rejected_text = text_for(pair, "rejected")
            pi_c = seq_logp(policy, chosen_text)
            pi_r = seq_logp(policy, rejected_text)
            with torch.no_grad():
                ref_c = seq_logp(ref, chosen_text)
                ref_r = seq_logp(ref, rejected_text)
            logits = beta * ((pi_c - ref_c) - (pi_r - ref_r))
            loss = -F.logsigmoid(logits) * float(pair.get("weight", 1.0))
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item()
        print(
            f"epoch {epoch + 1}/{epochs}: mean DPO loss "
            f"{total / len(pairs):.4f}",
            file=sys.stderr,
        )

    policy.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    print(f"saved DPO-tuned proposer -> {out_dir}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="python -m maverick.training.rlaif",
        description="RLAIF/DPO loop on the proposer using verifier rewards.",
    )
    ap.add_argument(
        "--data", required=True, type=Path,
        help="Klear-format JSONL of trajectories (from training.ingest).",
    )
    ap.add_argument(
        "--base-model", required=True,
        help="HF model id or local path for the proposer to fine-tune.",
    )
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output directory for the DPO-tuned proposer.",
    )
    ap.add_argument("--beta", type=float, default=0.1,
                    help="DPO KL temperature (default 0.1).")
    ap.add_argument("--epochs", type=int, default=1,
                    help="Number of passes over the pairs (default 1).")
    ap.add_argument("--lr", type=float, default=5e-7,
                    help="AdamW learning rate (default 5e-7).")
    ap.add_argument("--min-margin", type=float, default=0.5,
                    help="Min reward gap for a preference pair (default 0.5).")
    ap.add_argument("--max-pairs", type=int, default=32,
                    help="Max pairs per task_family (default 32).")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    rows = load_klear(args.data)
    pairs = build_preference_pairs(
        rows,
        min_margin=args.min_margin,
        max_pairs_per_group=args.max_pairs,
    )
    print(
        f"built {len(pairs)} preference pairs from {len(rows)} trajectories",
        file=sys.stderr,
    )
    rows_by_id = {r.get("id"): r for r in rows}
    return train(
        pairs,
        base_model=args.base_model,
        out_dir=args.out,
        rows_by_id=rows_by_id,
        beta=args.beta,
        epochs=args.epochs,
        lr=args.lr,
    )


if __name__ == "__main__":
    sys.exit(main())
