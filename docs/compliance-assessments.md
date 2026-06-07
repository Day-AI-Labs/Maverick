# Compliance assessments

Maverick can **conduct** structured compliance assessments of a subject — a
processing activity, an AI system, or a vendor — running a questionnaire, scoring
each answer, and producing a completed assessment with **findings** and an overall
**risk rating**. This is distinct from [`maverick ropa` / `dpia` / `ai-act`](regulated-deployment.md#records-of-processing-art-30),
which scaffold a document from Maverick's *own* deployment config — assessments
evaluate an arbitrary third-party subject.

## Built-in assessments

| Type | What it assesses | Framework |
|---|---|---|
| `pia` | A processing activity (Privacy Impact Assessment) | ISO 29134 / GDPR Art. 35 |
| `aira` | An AI system (AI Risk Assessment) | NIST AI RMF / EU AI Act |
| `vendor_risk` | A third-party vendor | TPRM |

New assessment types are added as data (a list of questions), not code.

## Conduct one

```bash
maverick assess templates                       # list the assessment types
maverick assess questions vendor_risk           # see the questionnaire (--format json for tools)
maverick assess score vendor_risk \
    --subject "Acme Corp" --answers answers.json # score it -> findings + risk rating (and save)
maverick assess list                            # saved assessments, newest first
maverick assess show <id>                        # a saved result
```

`answers.json` maps each question id to an answer:

```json
{
  "vr_dpa": "no",
  "vr_soc2": "no",
  "vr_breach_history": "yes",
  "vr_subprocessors": {"answer": "unknown", "note": "no list provided"}
}
```

An answer is `yes` / `no` / `na` / `unknown`. Each question declares which answer
is the *risk* answer and at what severity; giving it raises a finding. `unknown`
raises an **unverified** finding (a diligence gap); `na` and the safe answer clear
it. The overall rating is the highest finding severity present (`high` / `medium` /
`low` / `minimal`).

```text
Vendor Risk Assessment: Acme Corp
Risk rating: HIGH
Completeness: 9/10 answered, 5 finding(s)

  [HIGH]   Contractual: Is a data-processing agreement (DPA) in place with the vendor?
      -> Execute a DPA before sharing personal data (Art. 28).
  [MEDIUM] History: Has the vendor had a reported data breach in the last 24 months?
      -> Review the breach, root cause, and remediation.
  ...
```

Results are saved under `~/.maverick/assessments/<id>.json`.

## Conducted by the agent

The same engine backs the **assessment agent**: Maverick can be told "run a vendor
risk assessment of Acme" and it drives the questionnaire itself — filling answers
from the documents and context it's given, flagging what it can't verify, and
producing the scored result for a human to review. The agent never signs off the
assessment; it produces the draft and the findings.

!!! note
    Assessments are a structured-diligence aid, not legal advice. A qualified
    reviewer (DPO / counsel) owns the conclusions.
