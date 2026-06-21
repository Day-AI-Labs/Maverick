# Shield Cheap-Probe Trained Classifier — Recommendation

> Research output. Decision-ready. Network was available during research
> (HuggingFace MCP + web search both responded), so dataset sizes/licenses
> below are confirmed against live Hub metadata (June 2026). No code changed.

## Context: the integration seam (read this first)

The seam is `packages/maverick-shield/maverick_shield/probe_model.py`. A model
is a plain-JSON artifact — **no pickle** (loading operator pickle into a safety
component is code execution) — of the shape:

```json
{"bias": -1.2, "weights": {"feature_name": 2.3, "...": 1.1}, "threshold": 0.5}
```

`LinearProbeModel.score(text) = sigmoid(bias + Σ weights[f]·features[f])`,
returning a probability in `[0,1]`. The cascade ensembles it with the
regex/unicode heuristic by **MAX**, so a model can only *raise* recall, never
lower the heuristic floor. Default OFF.

**The load-bearing constraint everyone misses:** today `probe_features(text)`
emits exactly **7 fixed features** — `regex_hit`, `unicode_tag`, `zero_width`,
`base64_blob`, `hex_escape`, `non_ascii_ratio`, `log_length`. A model scores
over *those names only*; unknown weight keys are silently ignored
(`feats.get(name, 0.0)`). So any model that needs lexical content (n-grams,
token presence) **cannot be expressed in the current feature space** — the
recommendation below addresses exactly that gap.

---

## 1. Datasets

All are public, English, prompt-injection / jailbreak labelled. "Benign
negatives" matters because we need a low false-positive floor on ordinary text.
Sizes/licenses confirmed via HuggingFace Hub metadata.

| Dataset | Approx size | License | Benign negatives? | Source URL |
|---|---|---|---|---|
| **guychuk/benign-malicious-prompt-classification** | 464.5K rows (single train split) | Apache-2.0 ✅ commercial-OK | **Yes** — `label` is a `benign`/`malicious` ClassLabel; large benign pool | https://huggingface.co/datasets/guychuk/benign-malicious-prompt-classification |
| **jackhhao/jailbreak-classification** | ~1.3K (1.0K train / 262 test) | Apache-2.0 ✅ | **Yes** — `type` ∈ {jailbreak, benign} | https://huggingface.co/datasets/jackhhao/jailbreak-classification |
| **deepset/prompt-injections** | 662 (546 train / 116 test) | Apache-2.0 ✅ | **Yes** — `label` 0/1, both classes | https://huggingface.co/datasets/deepset/prompt-injections |
| **JasperLS/prompt-injections** | 662 (546/116) — predecessor/mirror of deepset | No license tag ⚠️ (treat as unlicensed; use deepset's instead) | Yes | https://huggingface.co/datasets/JasperLS/prompt-injections |
| **TrustAIRLab/in-the-wild-jailbreak-prompts** ("Do Anything Now", CCS'24) | 21.5K total: 1.4K jailbreak + ~13.7K **regular** prompts | MIT ✅ | **Yes** — separate `regular_*` configs are real-world benign prompts; `jailbreak` bool flag | https://huggingface.co/datasets/TrustAIRLab/in-the-wild-jailbreak-prompts |
| **Lakera/gandalf_ignore_instructions** | ~1.0K (777/111/112) | MIT ✅ | **No** — injections only (positives); pair with benign from another set | https://huggingface.co/datasets/Lakera/gandalf_ignore_instructions |
| **hackaprompt/hackaprompt-dataset** (EMNLP'23) | 601.8K competition submissions | MIT ✅ but **🔒 gated** (login/accept) | Mostly attack attempts; `correct` bool can derive labels | https://huggingface.co/datasets/hackaprompt/hackaprompt-dataset |
| **rogue-security/prompt-injections-benchmark** (was Qualifire) | 5.0K (jailbreak/benign) | **CC-BY-NC-4.0 ❌ non-commercial** + 🔒 gated | Yes | https://huggingface.co/datasets/rogue-security/prompt-injections-benchmark |

**Recommended training mix (all Apache-2.0 / MIT, commercial-safe):**
`guychuk` (the volume + balanced benign/malicious backbone) +
`TrustAIRLab` regular-vs-jailbreak (real-world distribution shift, strong benign
negatives) + `deepset` and `jackhhao` (curated injection/jailbreak, clean test
sets) + `Lakera/gandalf` positives. This gives ~480K+ rows with abundant benign
negatives and no commercial-licensing risk.

**Hard negatives to add by hand** (these drive the false-positive floor):
security docs, CVE write-ups, pentest tutorials, base64/hex code snippets,
non-English/emoji-heavy benign text — exactly the things that trip the
heuristic's `regex_hit` / `non_ascii_ratio` / `base64_blob` features. The
`prodnull/prompt-injection-repo-dataset` notes doing this deliberately; mirror
the idea.

---

## 2. Model recommendation

### Option (a) — char/word n-gram TF-IDF + logistic regression, exported as JSON weights

A logistic regression is *already* the exact math the seam computes
(`sigmoid(bias + Σ w·x)`). The only mismatch is the **feature space**: TF-IDF
n-grams produce thousands of `(ngram → weight)` pairs, but
`probe_features()` only emits the 7 hand-named signals. So a TF-IDF model does
**not** drop into the seam *as written* — its weight keys would all be ignored.

There are two clean ways to make it fit, in order of preference:

- **(a1) Extend `probe_features()` to also emit hashed character n-gram
  features with deterministic, content-derived names**, e.g.
  `cng:<h>` where `<h> = md5(ngram) % N` for N≈4096–16384 buckets (the
  hashing trick). Train sklearn `HashingVectorizer(analyzer="char_wb",
  ngram_range=(3,5), n_features=N, alternate_sign=False)` → `LogisticRegression`,
  then export `{"cng:0": w0, ...}` + the 7 existing signal weights. This keeps
  the JSON-linear, no-pickle, CPU, offline contract **exactly** and is a purely
  additive feature change (existing 7-feature models still load). This is the
  primary recommendation.
- **(a2) Keep only the 7 features** and just fit a logistic regression over
  them. Zero seam change, but the ceiling is low — it's the heuristic with
  learned weights, and since we MAX-ensemble with the heuristic anyway, it adds
  almost no recall. Use only as a trivial first artifact / smoke test.

Why linear wins here: it is *natively* the JSON-weights format, has no runtime
dependency (scoring is a dict dot-product in pure Python — already implemented),
is microseconds-per-input on CPU, fully offline, and trivially auditable (you
can read the weights). For a *cheap-probe tier that MAX-ensembles* — i.e. only
needs to add recall on top of a strong heuristic floor, not be a standalone
SOTA detector — a hashed char-n-gram LR is the right altitude.

### Option (b) — small distilled transformer (tiny/DistilBERT, e.g. `fmops/distilbert-prompt-injection`, `deepset/deberta-v3-base-injection`, ProtectAI deberta)

Higher accuracy ceiling and better generalization to paraphrased/novel attacks.
But it **breaks every constraint of the seam**:

- Not expressible as JSON linear weights → requires shipping model weights
  (safetensors, not pickle — but still a new artifact format and loader).
- Needs `torch`/`transformers` (or ONNX Runtime) on the hot path — a heavy new
  top-level dependency (violates kernel rule 5: no new top-level dep without a
  config knob, and this is a *fat* one), larger install, slower cold start.
- Per-input latency is milliseconds, not microseconds, on CPU — wrong tier for a
  *cheap* per-input probe.
- The no-pickle safety property would have to be re-established for a new format,
  and the "operator can supply their own model" story gets much harder to keep
  safe.

A transformer is the right choice for an *expensive* probe tier or an offline
batch re-scorer, not for this seam. Pretrained injection DeBERTa/DistilBERT
checkpoints also carry their own license review (see §4).

### Primary recommendation

**Train a hashed char-word n-gram TF-IDF + L2-regularized logistic regression,
export as JSON weights (Option a1), after a small additive extension of
`probe_features()` to emit deterministic hashed n-gram features alongside the
existing 7 signals.** It is the only option that preserves the seam's core
guarantees (JSON-linear, no-pickle, pure-Python CPU scoring, offline,
auditable, fail-open) while materially raising recall over the heuristic. Defer
a transformer to a future *separate* expensive-probe tier if eval shows the
linear model plateaus on novel/obfuscated attacks.

---

## 3. Training approach

**Features**
- Keep the 7 existing signals (they're cheap and already MAX-ensembled — let the
  LR re-weight them).
- Add char-word n-grams via `HashingVectorizer(analyzer="char_wb",
  ngram_range=(3,5), n_features≈8192, alternate_sign=False, norm="l2")`. Char
  n-grams are robust to spacing/obfuscation/leet-speak common in jailbreaks and
  need no vocabulary file (hashing → fixed, content-derived keys, no pickle).
- Optionally add word (1,2)-grams in a second hash band for phrase signals
  ("ignore previous instructions", "you are now DAN").
- Feature names in the JSON must be the deterministic hash keys the *extended*
  `probe_features()` will reproduce at inference — the names are the contract.

**Calibration to [0,1]**
- LR already outputs a probability via sigmoid, but raw LR probabilities are
  often poorly calibrated on imbalanced data. Fit **Platt scaling**
  (`sklearn.calibration.CalibratedClassifierCV(method="sigmoid", cv=5)`) on a
  held-out fold. Because Platt scaling is itself `sigmoid(A·logit + B)`, fold
  `A`/`B` back into the exported `bias` and `weights` so the artifact stays a
  single linear+sigmoid — no extra runtime step. (Isotonic would not fold into
  linear weights; avoid it for this seam.)

**Threshold selection**
- `threshold` in the JSON is advisory (the cascade uses the raw probability and
  MAXes it), but set it meaningfully: pick the operating point on the
  precision-recall curve that holds **benign false-positive rate ≤ a hard floor
  (target ≤ 0.5–1%)** measured on held-out benign text, then take the highest
  recall available at that FPR. Report the chosen probability and its FPR/recall
  in the artifact metadata.

**Train/test split**
- **Split by source and by attack family, not random row shuffle**, to avoid
  leakage (in-the-wild jailbreaks share near-duplicate templates; random splits
  inflate scores). Hold out entire datasets/configs as the test set
  (e.g. train on `guychuk` + `TrustAIRLab` + `Lakera`, test on `deepset` and
  `jackhhao` *test* splits) to measure cross-distribution generalization.
- De-duplicate near-identical prompts (minhash/normalized exact-match) before
  splitting.

**Avoid overfitting**
- Strong L2 (`C` tuned by CV), modest `n_features` (8K–16K buckets), no raw
  vocabulary. Prefer a *smaller* model that generalizes — we only need
  incremental recall over the heuristic.
- Class weighting (`class_weight="balanced"`) since benign vastly outnumbers
  attacks in the realistic mix.
- Watch for the model just relearning `regex_hit`; inspect top weights.

**Evaluation**
- Primary: **precision/recall and PR-AUC on a held-out, source-disjoint test
  set**, plus recall at the fixed ≤1% benign-FPR operating point.
- **Benign false-positive floor**: evaluate on a *clean benign corpus the model
  never saw* (e.g. ordinary support tickets, code snippets, CVE text,
  non-English) and confirm FPR stays under the floor — this is the gate for
  "good enough to ship ON by default."
- **Ensemble eval**: measure the MAX-ensemble (model OR heuristic), not the
  model alone — the ship criterion is "recall improves and benign FPR does not
  regress versus heuristic-only."
- Sanity-check the seam: the exported JSON must round-trip through
  `LinearProbeModel.from_dict` and produce identical scores to the trained
  sklearn pipeline on a held-out batch.

---

## 4. Licensing / commercial-use caveats

Maverick is proprietary/commercial, so non-commercial and unlicensed assets are
disqualified for the *bundled, ship-by-default* model.

- **❌ `rogue-security/prompt-injections-benchmark` (ex-Qualifire) — CC-BY-NC-4.0,
  non-commercial.** Do **not** train the shipped model on it. Also gated. Use it
  only for internal eval if at all, and not in any bundled artifact.
- **⚠️ `JasperLS/prompt-injections` — no license tag.** Treat as all-rights-
  reserved; use the Apache-2.0 `deepset/prompt-injections` (same 662 rows)
  instead.
- **⚠️ `hackaprompt/hackaprompt-dataset` — MIT but gated** (must accept terms /
  authenticate to download). MIT is commercial-OK, but the gate means it can't be
  pulled in an unauthenticated CI build; fetch once, vet, and vendor if used.
- **✅ Commercial-safe (Apache-2.0 / MIT):** `guychuk`, `jackhhao`, `deepset`,
  `TrustAIRLab/in-the-wild-jailbreak-prompts`, `Lakera/gandalf_ignore_instructions`.
  These cover the full training mix with no NC restriction.
- **Pretrained-model caveat (only relevant if Option (b) is ever pursued):**
  vet each checkpoint's license individually — many injection-detection DeBERTa
  models are derived from `microsoft/deberta-v3` (MIT) but some published
  fine-tunes attach Apache-2.0 or custom/RAIL terms; a RAIL "no-harmful-use"
  clause can be awkward for a security product. The recommended linear path
  trains weights from scratch and ships only numbers, sidestepping pretrained-
  model licensing entirely.

Even with permissive licenses, retain provenance (dataset name + license +
commit) alongside the artifact so the bundled model's training data is auditable
— consistent with Maverick's "signed learning audit" posture.

---

## 5. Bottom line

Train a **hashed char/word n-gram TF-IDF + L2 logistic regression** and export
it as the seam's JSON `{bias, weights, threshold}` — it *is* natively the
sigmoid-linear math `probe_model.py` already computes, runs in microseconds in
pure Python on CPU with zero new runtime deps, stays offline, has no pickle, and
remains auditable. The one required change is **additive**: extend
`probe_features()` to also emit deterministic hashed n-gram features (the
current 7 hand-named signals alone cannot carry lexical content), which keeps
all existing models loadable. Build the training set from commercial-safe
Apache-2.0/MIT data — `guychuk` (~464K, balanced benign/malicious),
`TrustAIRLab` in-the-wild (real benign + jailbreak), `deepset`, `jackhhao`, and
`Lakera/gandalf` — and **exclude the CC-BY-NC `rogue-security`/Qualifire and the
untagged `JasperLS` sets**. Gate the ship-by-default decision on a hard **≤1%
benign false-positive floor** measured on unseen benign text with the MAX-
ensemble (model OR heuristic), splitting by source/attack-family to avoid
leakage; defer a transformer to a future separate *expensive*-probe tier only if
the linear model plateaus on novel obfuscated attacks.
