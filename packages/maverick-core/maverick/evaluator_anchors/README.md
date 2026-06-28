# Evaluator ground-truth anchors

Each `*.ndjson` file here is the fixed, held-out **anchor** for one evaluator
role (the file stem is the role, e.g. `paper_reviewer.ndjson`). It is the
ground truth a learned evaluator must agree with before it can be promoted over
the incumbent — see `maverick.evaluator_evolution` and the design note in
[`docs/proposals/evaluator-co-evolution.md`](../../../../docs/proposals/evaluator-co-evolution.md).

One JSON object per line:

```json
{"id": "rev-0001", "label": true,  "prompt": "<optional artifact text>"}
{"id": "rev-0002", "label": false, "prompt": "..."}
```

- `id` — stable identifier for the datum (immutable once released).
- `label` — the correct verdict (e.g. accept = `true`, reject = `false`).
- `prompt` — optional context shown to the evaluator; excluded from the checksum
  (editing the artifact text does not move the decision boundary; flipping a
  label or dropping an item does).

## The anchor is the guardrail

A weak, mutable, or poisoned anchor turns provable learning into laundered
drift (arXiv 2606.26294). Released anchors are therefore **immutable**, pinned
by checksum in `../evaluator_anchors.lock.json` exactly as released world-model
migrations are. After adding or extending an anchor, regenerate the lock so the
change is reviewed:

```
python -m maverick.evaluator_evolution --regen   # rewrite the lock
python -m maverick.evaluator_evolution --ci       # CI gate: fail on any drift
```

This directory is intentionally empty of data by default — anchors are
deployment-specific ground truth. The empty baseline lock keeps the CI gate
green until you commit your first anchor.
