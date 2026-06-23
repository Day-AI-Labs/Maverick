"""Department bundles: the specialist packs as deployable teams.

One specialist pack is a single hire; a *department* is the whole team. This
module groups the built-in specialist packs (:mod:`maverick.domain`) by their
business *suite* into named, deployable units — "Finance", "Sales & GTM" — each
with a human-readable charter and a roster. It is the buyable-team layer the
dashboard and installer present on top of the 1,000+ packs: pick a department,
deploy its roster, and a fleet of specialists comes up together.

Read-only over the pack registry — assembling a department never mutates a pack.
Suites turned off in ``[suites]`` config drop out (via
:func:`maverick.domain.enabled_domains`), so a department reflects what the
operator has actually enabled, not the full catalog.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .domain import SUITE_PREFIXES, DomainProfile, enabled_domains, suite_for

# Human-facing label + one-line charter per suite key (the value side of
# ``SUITE_PREFIXES``). A suite missing here still resolves to a derived title
# (``key.replace("_", " ").title()``), so adding a suite prefix never crashes
# this layer — it just reads better once a charter is authored.
SUITE_LABELS: dict[str, tuple[str, str]] = {
    "finance": ("Finance",
                "Close the books, forecast, and control spend — FP&A, "
                "controllership, treasury, and SOX."),
    "operations": ("Operations",
                    "Run and improve the operating core — process mapping, "
                    "S&OP, and continuous improvement."),
    "legal": ("Legal",
              "Contracts, corporate governance, and compliance — drafted and "
              "reviewed, never sent without a human."),
    "it_grc": ("IT & GRC",
               "IT service management, risk, and controls — tickets, access, "
               "and audit-ready governance."),
    "sales_gtm": ("Sales & GTM",
                  "Pipeline from first touch to close — demand gen, "
                  "sequencing, deal desk, and onboarding."),
    "hr": ("People & HR",
           "Talent, performance, and employee experience across the "
           "employee lifecycle."),
    "product_engineering": ("Product & Engineering",
                            "Build, review, and ship — APIs, code review, and "
                            "continuous delivery."),
    "strategy": ("Strategy",
                 "Strategic analysis and transformation — market "
                 "intelligence, M&A support, and board-ready cases."),
    "customer_experience": ("Customer Experience",
                            "Support and success that scales — triage, "
                            "resolution, and retention."),
    "marketing": ("Marketing",
                  "Brand, content, and campaigns — editorial calendars, SEO, "
                  "and channel performance."),
    "procurement": ("Procurement",
                    "Strategic sourcing and supplier management — RFPs, "
                    "negotiation, and spend control."),
    "data_analytics": ("Data & Analytics",
                       "Trusted data — governance, quality, cataloging, and "
                       "analysis."),
    "security_ops": ("Security Operations",
                     "24/7 security posture — SOC monitoring, incident "
                     "response, and remediation."),
    "executive_office": ("Executive Office",
                         "Coordinate the firm — exec assistance, "
                         "cross-functional alignment, and reporting."),
    "facilities_ehs": ("Facilities & EHS",
                       "Facilities, environment, health, and safety — "
                       "compliant and audit-ready."),
    "healthcare": ("Healthcare",
                   "Clinical and administrative workflows for healthcare "
                   "operations."),
    "insurance": ("Insurance",
                  "Underwriting, claims, and policy operations."),
    "banking": ("Banking",
                "Retail and commercial banking operations and regulatory "
                "preparation."),
    "retail": ("Retail",
               "Merchandising, replenishment, and store operations."),
    "manufacturing_vertical": ("Manufacturing",
                               "Production, BOM/routing, and plant "
                               "operations."),
    "construction": ("Construction",
                     "Project delivery, estimating, and field operations."),
    "logistics": ("Logistics",
                  "Transportation, track-and-trace, and fulfillment."),
    "professional_services": ("Professional Services",
                              "Engagement delivery, utilization, and client "
                              "operations."),
    "government_contracting": ("Government Contracting",
                               "Capture, compliance, and contract delivery "
                               "for public-sector work."),
    "education_nonprofit": ("Education & Nonprofit",
                            "Program delivery, accommodations, and grant "
                            "operations."),
    "tax": ("Tax",
            "Tax preparation, provision, and compliance across "
            "jurisdictions."),
    "utilities": ("Utilities",
                  "Regulated utility operations and field service."),
    "real_estate": ("Real Estate",
                    "Asset, lease, and property operations."),
    "pharma_lifesciences": ("Pharma & Life Sciences",
                            "Regulated R&D, quality, and commercial "
                            "operations."),
    "telecom_media": ("Telecom & Media",
                      "Network, content, and subscriber operations."),
    "hospitality": ("Hospitality",
                    "Guest, property, and service operations."),
    "capital_markets": ("Capital Markets",
                        "Trading, surveillance, and market operations."),
}


def department_title(key: str) -> str:
    """Display name for a suite key, derived from the key when unlabeled."""
    label = SUITE_LABELS.get(key)
    return label[0] if label else key.replace("_", " ").title()


def department_charter(key: str) -> str:
    """One-line charter for a suite key (empty when unlabeled)."""
    label = SUITE_LABELS.get(key)
    return label[1] if label else ""


@dataclass
class Department:
    """A business suite presented as a deployable team of specialist packs."""
    key: str                                   # suite key, e.g. "finance"
    title: str
    charter: str
    members: list[str] = field(default_factory=list)   # pack names, sorted

    @property
    def headcount(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "title": self.title,
            "charter": self.charter,
            "headcount": self.headcount,
            "members": list(self.members),
        }


def _group(cfg: dict | None) -> dict[str, list[str]]:
    """Map suite key -> sorted pack names, over the *enabled* packs only.

    Packs with no recognized suite prefix (legacy/generic) are skipped — a
    department is a suite, and those packs belong to no suite."""
    by_suite: dict[str, list[str]] = {}
    for name in enabled_domains(cfg):
        suite = suite_for(name)
        if suite is None:
            continue
        by_suite.setdefault(suite, []).append(name)
    for names in by_suite.values():
        names.sort()
    return by_suite


def list_departments(cfg: dict | None = None) -> list[Department]:
    """Every enabled department, sorted by title.

    A suite whose packs are all disabled simply does not appear. Backward
    compatible with no ``[suites]`` config (every suite present)."""
    grouped = _group(cfg)
    out = [
        Department(
            key=key,
            title=department_title(key),
            charter=department_charter(key),
            members=names,
        )
        for key, names in grouped.items()
    ]
    out.sort(key=lambda d: d.title)
    return out


def get_department(key: str, cfg: dict | None = None) -> Department | None:
    """A single department by suite key, or ``None`` if it has no enabled packs."""
    if key not in SUITE_PREFIXES.values():
        return None
    names = _group(cfg).get(key)
    if not names:
        return None
    return Department(
        key=key,
        title=department_title(key),
        charter=department_charter(key),
        members=names,
    )


def roster(key: str, cfg: dict | None = None) -> list[DomainProfile]:
    """The specialist :class:`~maverick.domain.DomainProfile` objects for a
    department — the team you would deploy as a fleet."""
    dept = get_department(key, cfg)
    if dept is None:
        return []
    domains = enabled_domains(cfg)
    return [domains[name] for name in dept.members if name in domains]


# ---------------------------------------------------------------------------
# Deploy a department as a fleet — a PAID ADD-ON.
#
# Departments are not bundled with the base product: a tenant deploys one only
# when its plan carries the ``departments`` add-on (or a per-department
# ``department:<key>`` grant). The gate is :func:`maverick.billing.feature_allowed`,
# which fails OPEN for self-host / single-tenant / unprovisioned deployments and
# closed only for a tenant an operator has explicitly put on a limited plan —
# so this never breaks a self-hoster, and always bills a managed tenant.
# ---------------------------------------------------------------------------
DEPARTMENTS_FEATURE = "departments"


class EntitlementError(RuntimeError):
    """The active tenant's plan does not include the departments add-on."""

    def __init__(self, key: str, *, feature: str = DEPARTMENTS_FEATURE) -> None:
        self.department = key
        self.feature = feature
        super().__init__(
            f"the {key!r} department is a paid add-on; the active plan does not "
            f"include the {feature!r} entitlement"
        )


def department_entitled(key: str, *, tenant: str | None = None) -> bool:
    """Whether the active (or given) tenant may deploy department ``key``.

    Granted by the whole-catalog ``departments`` add-on OR a per-department
    ``department:<key>`` feature. Fail-open for self-host/unprovisioned tenants
    (see :func:`maverick.billing.feature_allowed`)."""
    from .billing import feature_allowed
    return (feature_allowed(DEPARTMENTS_FEATURE, tenant=tenant)
            or feature_allowed(f"department:{key}", tenant=tenant))


def fleet_from_department(dept: Department, owner: str, *,
                          cfg: dict | None = None, name: str | None = None):
    """Build (but do not save or entitle) a :class:`~maverick.fleet.Fleet` whose
    agents are the department's specialists.

    Each pack becomes one agent: ``name`` = pack name (its run principal),
    ``role`` = the department key (so an operator scopes the whole team with one
    ``[roles.<key>]`` block), ``description`` = the pack's charter line. Packs
    with a name that is not a valid fleet-agent identifier are skipped."""
    from .fleet import Fleet, FleetAgent, valid_name
    domains = enabled_domains(cfg)
    agents = tuple(
        FleetAgent(name=m, role=dept.key,
                   description=(domains[m].description or "")[:200])
        for m in dept.members
        if m in domains and valid_name(m)
    )
    return Fleet(name=name or f"dept-{dept.key}", owner=owner, agents=agents)


def deploy_department(key: str, owner: str, *, cfg: dict | None = None,
                      tenant: str | None = None, name: str | None = None,
                      save: bool = True):
    """Deploy a department as a fleet of its specialists.

    Entitlement-gated: raises :class:`EntitlementError` when the tenant's plan
    lacks the ``departments`` add-on. Returns ``None`` if the department has no
    enabled packs; otherwise the saved :class:`~maverick.fleet.Fleet`."""
    dept = get_department(key, cfg)
    if dept is None:
        return None
    if not department_entitled(key, tenant=tenant):
        raise EntitlementError(key)
    fleet = fleet_from_department(dept, owner, cfg=cfg, name=name)
    if save:
        from .fleet import save_fleet
        save_fleet(fleet, tenant=tenant or "__active__")
    return fleet
