"""Skill auto-generation.

After a goal completes successfully, ask a distiller model to extract a
reusable SKILL.md from the trajectory. On the next run, relevant skills
are loaded into the orchestrator's context, so successful patterns
compound over time.

This is the closed-loop learning piece. Hermes does it; Maverick does it
better because the orchestrator-blackboard structure gives us a clean
trajectory to distill.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .blackboard import Blackboard
from .budget import Budget
from .llm import LLM, MODEL_SONNET


SKILLS_DIR = Path.home() / ".maverick" / "skills"


DISTILLER_SYSTEM = """You distill successful agent trajectories into reusable SKILL.md files.

Output format: a markdown file with YAML frontmatter, exactly:

---
name: <short-kebab-case-id>
triggers:
  - <natural language phrase that should activate this skill>
  - <another phrase>
tools_needed:
  - <tool name>
---

# What this skill does

<one paragraph describing the goal class>

# Steps

1. <step>
2. <step>
3. <step>

# Notes

<gotchas, anti-patterns, things that did NOT work>

Be specific. Cite exact tool calls, exact commands. Skills are only useful if a future agent can follow them mechanically."""


@dataclass
class Skill:
    name: str
    triggers: list[str]
    tools_needed: list[str]
    body: str
    path: Path

    @classmethod
    def parse(cls, text: str, path: Path) -> "Skill":
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not m:
            raise ValueError("missing YAML frontmatter")
        front, body = m.group(1), m.group(2)
        meta: dict = {}
        current_key = None
        for line in front.splitlines():
            line = line.rstrip()
            if not line:
                continue
            if line.startswith("  - ") and current_key:
                meta.setdefault(current_key, []).append(line[4:].strip())
            elif ":" in line:
                k, _, v = line.partition(":")
                k = k.strip()
                v = v.strip()
                current_key = k
                if v:
                    meta[k] = v
                else:
                    meta[k] = []
        return cls(
            name=meta.get("name", path.stem),
            triggers=meta.get("triggers", []) if isinstance(meta.get("triggers"), list) else [],
            tools_needed=meta.get("tools_needed", []) if isinstance(meta.get("tools_needed"), list) else [],
            body=body.strip(),
            path=path,
        )


def load_skills(skills_dir: Path = SKILLS_DIR) -> list[Skill]:
    if not skills_dir.exists():
        return []
    out = []
    for p in skills_dir.glob("*.md"):
        try:
            out.append(Skill.parse(p.read_text(), p))
        except Exception:
            continue
    return out


def relevant_skills(goal: str, all_skills: list[Skill], max_n: int = 3) -> list[Skill]:
    """Cheap lexical match. Good enough until embeddings land."""
    goal_lower = goal.lower()
    goal_words = set(re.findall(r"\w+", goal_lower))

    scored: list[tuple[int, Skill]] = []
    for s in all_skills:
        score = 0
        for trig in s.triggers:
            trig_words = set(re.findall(r"\w+", trig.lower()))
            score += len(trig_words & goal_words) * 2
            if trig.lower() in goal_lower:
                score += 5
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    return [s for _, s in scored[:max_n]]


def render_for_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""
    parts = ["# Relevant skills from past runs", ""]
    for s in skills:
        parts.append(f"## {s.name}")
        parts.append(s.body)
        parts.append("")
    return "\n".join(parts)


def distill(
    goal: str,
    summary: str,
    blackboard: Blackboard,
    llm: LLM,
    budget: Optional[Budget] = None,
    skills_dir: Path = SKILLS_DIR,
) -> Optional[Skill]:
    """After a successful run, ask the model to extract a SKILL.md."""
    skills_dir.mkdir(parents=True, exist_ok=True)

    trajectory = blackboard.render(200)
    prompt = (
        f"Goal: {goal}\n\n"
        f"Outcome summary:\n{summary}\n\n"
        f"Trajectory (blackboard):\n{trajectory}\n\n"
        "Distill this into a SKILL.md file that would let a future agent "
        "solve a similar goal faster. Only output the markdown."
    )

    resp = llm.complete(
        system=DISTILLER_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        budget=budget,
        max_tokens=2048,
        model=MODEL_SONNET,
    )
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("markdown"):
            text = text[len("markdown") :]
        text = text.strip()

    try:
        # Extract name from frontmatter to pick filename.
        m = re.search(r"^name:\s*(\S+)", text, re.MULTILINE)
        name = m.group(1) if m else "skill"
        name = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-") or "skill"
        path = skills_dir / f"{name}.md"
        path.write_text(text)
        return Skill.parse(text, path)
    except Exception:
        return None
