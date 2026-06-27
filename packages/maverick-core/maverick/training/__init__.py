"""Training pipeline scaffold for Maverick RL fine-tuning.

Karpathy: "the only piece that earns ML complexity" is the
trajectory donation flywheel + a learned what-to-keep gate +
process-reward training. This package is where that work lands.

Layout:

  __init__.py     (this file)
  schema.py       Klear-AgentForge-compatible trajectory schema
  ingest.py       Read donated trajectories from outbox + dedup + label
  export_texts.py Export proposer_texts.jsonl (raw transcripts from the
                  world model) for real-text DPO; keyed to ingest's ids.
  prm_train.py    Train an AgentPRM head from labeled trajectories
                  (arxiv:2511.08325 protocol; torch MLP head).
  prm_linear.py   Train a torch-free linear AgentPRM head (plain JSON,
                  CPU-only) loadable by maverick.prm.LinearPRM.
  rlaif.py        RLAIF / DPO loop on the proposer using verifier
                  rewards as the signal.

Status (June 2026): SCHEMA + INGEST scaffolded; PRM_TRAIN implements the
AgentPRM head trainer (torch optional extra); RLAIF is a placeholder that
documents the next step. Real training requires GPU + trajectory volume
which is operator-side work, not in-kernel.
"""

__all__ = [
    "schema", "ingest", "export_texts", "prm_train", "prm_linear", "rlaif",
]
