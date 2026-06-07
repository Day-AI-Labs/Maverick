"""Finance platform controls — the governance wrapper for the CFO-office suite.

Per ``docs/proposals/finance-agent-suite.md``, the product is *not* the finance
agents (competent finance models are commodity) — it is the **governance
wrapper**: segregation of duties, maker-checker / dollar-threshold approvals, and
a tamper-evident book of record, enforced by the platform. This subpackage holds
the finance-specific platform pieces that sit on top of the already-shipped
primitives (``governance``, ``capability``, ``audit``, ``assessment``):

  * :mod:`maverick.finance.sod_linter` — segregation-of-duties conflict linter
    over the domain packs (the cardinal control, §2.1).
  * :mod:`maverick.finance.regimes` — finance compliance-regime packs (SOX, COSO,
    GAAP/IFRS, PCI, GLBA, AML, SEC, IRS) compiling to a governance ``Policy`` (§5).
  * :mod:`maverick.finance.status` — the ``finance status`` posture report (§5).
"""
from __future__ import annotations

__all__ = ["sod_linter", "regimes", "status"]
