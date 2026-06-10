# Office hours — cadence + format kit

**Roadmap ref:** 2027-H1 Distribution — "office hours".
**Status:** kit complete; the remaining work is scheduling the first session
and showing up every cycle after that. Lightweight by design.

A recurring, public, low-production video call where users and evaluators get
the maintainer for an hour. The value is reliability: same time, every cycle,
even when attendance is two people. Cancel-prone office hours are worse than
none.

## Cadence

- **Every 2 weeks, 60 minutes, fixed slot.** _Day/time and timezone:
  founder decision._ Alternate the slot between two timezones-friendly
  times if attendance shows demand (decide after 3 months of data, not
  before).
- Published as a standing calendar link in the README and docs site; one
  reminder post per session in whatever community venue exists at the time.
- Skip policy: announced ≥48h ahead, with the next date confirmed. Never
  silently no-show.

## Format (60 minutes)

| Minutes | Block |
|---|---|
| 0-5 | What shipped since last time — read straight from `CHANGELOG.md` / `FEATURES.md` diffs, no slides |
| 5-45 | Open queue: attendee questions, first-come; live debugging welcome (`maverick doctor` output is the standard first ask, per the bug-report convention in [`CONTRIBUTING.md`](../../CONTRIBUTING.md)) |
| 45-55 | One prepared 10-minute deep-dive on a real module or workflow (rotate: budget caps, audit verify, skills, plugins, sandboxes, channels) |
| 55-60 | Parking lot → GitHub issues, filed live; next session's date confirmed |

Rules of the room:

- **Not a sales call.** Licensing questions get the honest one-liner
  (proprietary, per-engagement, contact link) and move on; deals happen
  off-call.
- **No commitments on air.** Feature requests become issues, not promises;
  the [roadmap](../ROADMAP.md) is the backlog of record.
- **Security reports are redirected immediately** to
  [`SECURITY.md`](../../SECURITY.md), never discussed live.
- **Code of conduct applies** ([`CODE_OF_CONDUCT.md`](../../CODE_OF_CONDUCT.md));
  the host can remove anyone.
- Recording: **off by default** (people debug their own configs on screen);
  the prepared deep-dive segment may be recorded separately and published
  if it stands alone.

## Logistics

- Platform: anything with a stable recurring link and no attendee account
  wall. _Choice: founder._
- Host: the maintainer; a backup host only if one actually exists — don't
  block the program on staffing it.
- Prep per session: ≤30 minutes (changelog skim + the deep-dive).

## Measurement

Per session, one row in a log: attendance, questions asked, issues filed,
deep-dive topic. Review quarterly. Success looks like: repeat attendees,
issues that turn into PRs, and questions migrating from "how do I install"
to "how do I run this in my VPC" — evidence the audience is maturing toward
evaluation. If attendance is zero for 4 consecutive sessions, drop to
monthly rather than killing it.
