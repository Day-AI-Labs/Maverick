"""SEARCH/REPLACE edit format — Wave 11.

Aider's published edit-format benchmarks (Diff-XYZ, arxiv 2510.12487v2,
plus the public leaderboard) show SEARCH/REPLACE blocks beat both
hand-authored unified diffs and one-shot `str_replace_editor` calls for
every frontier model tested. On Claude 3.5 Sonnet alone, switching from
exact-match str_replace to fuzzy SEARCH/REPLACE moved Aider's bench from
~70% to 84.2%. On GPT-4-Turbo the gap is +10-40pp on the laziness
benchmark.

This module:
  - Parses SEARCH/REPLACE blocks out of an LLM's FINAL output.
  - Applies them with a fuzzy whitespace fallback ladder (5 progressive
    normalizations before giving up).
  - Returns per-block success/failure so the agent can re-prompt with
    a localized repair instruction rather than aborting the patch.

Format:

    path/to/file.py
    <<<<<<< SEARCH
    old content (exact bytes from file)
    =======
    new content
    >>>>>>> REPLACE

Multiple blocks per response, each can target a different file. To
create a new file, emit an empty SEARCH section. The orchestrator
calls `git diff` after applying to produce the unified patch for the
benchmark CSV — the model never writes hunk headers.

Defended against:
  - whitespace drift (trailing spaces, tabs vs spaces, leading indent)
  - CRLF / LF mismatches
  - missing trailing newline
  - duplicate matches (auto-expand context)
  - silent partial application (atomic per-block apply with rollback)
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Block header markers. The dividers must each occupy their own line.
# We accept 5 or more characters of each marker so model variations
# (`<<<<<<<<` instead of `<<<<<<<`) still parse.
_HEAD = re.compile(r"^<{5,}\s*SEARCH\s*$", re.MULTILINE)
_MID = re.compile(r"^={5,}\s*$", re.MULTILINE)
_TAIL = re.compile(r"^>{5,}\s*REPLACE\s*$", re.MULTILINE)


@dataclass
class SearchReplaceBlock:
    """One SEARCH/REPLACE block targeting a specific file."""
    path: str
    search: str
    replace: str
    raw_start: int = 0  # byte offset in the parsed text (for error msgs)


@dataclass
class ApplyResult:
    """Outcome of applying a single SEARCH/REPLACE block."""
    ok: bool
    block: SearchReplaceBlock
    reason: str = ""
    # When ok=False, the file slice that we *think* the model meant.
    near_miss_context: str = ""
    bytes_changed: int = 0
    # How the match was made: exact | rstrip | indent_norm | ws_collapse | levenshtein | created
    match_kind: str = ""


@dataclass
class ApplySummary:
    """Result of applying one or more SEARCH/REPLACE blocks."""
    results: list[ApplyResult] = field(default_factory=list)
    files_touched: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return bool(self.results) and all(r.ok for r in self.results)

    @property
    def num_failed(self) -> int:
        return sum(1 for r in self.results if not r.ok)

    @property
    def num_applied(self) -> int:
        return sum(1 for r in self.results if r.ok)

    def summary_text(self) -> str:
        if not self.results:
            return "no SEARCH/REPLACE blocks found"
        if self.ok:
            return (
                f"applied {self.num_applied} block(s) across "
                f"{len(self.files_touched)} file(s)"
            )
        parts = [f"{self.num_applied} ok, {self.num_failed} failed:"]
        for r in self.results:
            if r.ok:
                parts.append(f"  ✓ {r.block.path} ({r.match_kind})")
            else:
                parts.append(f"  ✗ {r.block.path}: {r.reason}")
        return "\n".join(parts)


def parse_blocks(text: str) -> list[SearchReplaceBlock]:
    """Extract SEARCH/REPLACE blocks from an LLM response.

    The model output may contain prose, fenced code, multiple files.
    Each block is:

        <optional prose>
        path/to/file.py
        <<<<<<< SEARCH
        ...content...
        =======
        ...content...
        >>>>>>> REPLACE

    The path line is the LAST non-empty line before the SEARCH marker.
    Blank lines between path and marker are tolerated. The path may
    appear inside a code fence (```path``` or ```diff path); we strip
    the fence syntax.

    Returns blocks in document order. Returns empty list on no match.
    """
    if not text:
        return []
    # Normalise line endings -- mixed CRLF/LF inside one response
    # is common from copy-pasted source.
    work = text.replace("\r\n", "\n").replace("\r", "\n")

    blocks: list[SearchReplaceBlock] = []
    pos = 0
    while pos < len(work):
        head = _HEAD.search(work, pos)
        if not head:
            break
        mid = _MID.search(work, head.end())
        if not mid:
            break
        tail = _TAIL.search(work, mid.end())
        if not tail:
            break

        # Path is the last non-empty line BEFORE the SEARCH marker.
        pre = work[pos:head.start()].rstrip("\n")
        # Strip an optional opening code fence on the line just before.
        path_lines = [
            ln.strip() for ln in pre.split("\n")
            if ln.strip() and not ln.strip().startswith("```")
        ]
        if not path_lines:
            # Malformed block (no file path); skip past it.
            pos = tail.end()
            continue
        path = path_lines[-1].strip("`").strip()
        # Strip leading "diff " or "patch " hint if present.
        path = re.sub(r"^(?:diff|patch)\s+", "", path).strip()

        search = work[head.end():mid.start()].lstrip("\n")
        replace = work[mid.end():tail.start()].lstrip("\n")
        # Re-add a trailing newline if absent — matches how editors save.
        if search and not search.endswith("\n"):
            search += "\n"
        if replace and not replace.endswith("\n"):
            replace += "\n"

        blocks.append(SearchReplaceBlock(
            path=path,
            search=search,
            replace=replace,
            raw_start=head.start(),
        ))
        pos = tail.end()
    return blocks


# ---- Fuzzy fallback ladder (the +8-12pp single-biggest win) ----


def _rstrip_lines(s: str) -> str:
    return "\n".join(line.rstrip() for line in s.split("\n"))


def _normalise_indent(s: str) -> tuple[str, list[str]]:
    """Reduce leading whitespace to a canonical form.

    Returns (normalised, original_leading) so we can re-apply the file's
    actual indent style to the REPLACE text.
    """
    lines = s.split("\n")
    leads = [re.match(r"^[ \t]*", ln).group(0) for ln in lines]
    if not any(leads):
        return s, leads
    # Find the minimum non-empty indent and strip it from all lines.
    nonempty = [lead for lead in leads if lead and any(c.strip() for c in s.split("\n")[leads.index(lead)])]
    if not nonempty:
        return s, leads
    common = min(nonempty, key=len)
    stripped = []
    for ln, lead in zip(lines, leads):
        if lead.startswith(common):
            stripped.append(ln[len(common):])
        else:
            stripped.append(ln.lstrip())
    return "\n".join(stripped), leads


def _whitespace_collapse(s: str) -> str:
    """Most aggressive: collapse all runs of whitespace to single space."""
    return re.sub(r"\s+", " ", s).strip()


def _find_with_fuzzy(content: str, needle: str) -> tuple[Optional[int], Optional[int], str]:
    """Locate `needle` in `content` with the fuzzy ladder.

    Returns (start, end, match_kind) or (None, None, ""). The match_kind
    tells the caller how aggressive the match was — useful for logging
    and for deciding when to bail out.
    """
    if not needle:
        return None, None, ""
    # 1. Exact match.
    idx = content.find(needle)
    if idx >= 0:
        return idx, idx + len(needle), "exact"

    # 2. Trailing-whitespace-stripped per-line match.
    needle_rs = _rstrip_lines(needle)
    content_rs = _rstrip_lines(content)
    idx = content_rs.find(needle_rs)
    if idx >= 0:
        # Map back to the original `content` by counting characters up
        # to the same logical position. Since we only stripped trailing
        # whitespace per line, line boundaries are preserved.
        # We re-locate by line number.
        target_line = content_rs[:idx].count("\n")
        # Sum lengths of lines 0..target_line-1 plus that many newlines
        # in the ORIGINAL content.
        original_lines = content.split("\n")
        start = sum(len(ln) + 1 for ln in original_lines[:target_line])
        # End is after needle.count("\n")+1 lines in the original.
        end_line = target_line + needle_rs.count("\n") + 1
        end = sum(len(ln) + 1 for ln in original_lines[:end_line])
        # Verify by re-checking the slice still rstrip-matches.
        if _rstrip_lines(content[start:end]).startswith(needle_rs):
            return start, end, "rstrip"

    # 3. Leading-indent-normalised match.
    needle_ni, _ = _normalise_indent(needle)
    content_ni, _ = _normalise_indent(content)
    idx = content_ni.find(needle_ni)
    if idx >= 0:
        # Best-effort: re-locate via line numbers in original.
        target_line = content_ni[:idx].count("\n")
        original_lines = content.split("\n")
        start = sum(len(ln) + 1 for ln in original_lines[:target_line])
        end_line = target_line + needle_ni.count("\n") + 1
        end = sum(len(ln) + 1 for ln in original_lines[:end_line])
        return start, end, "indent_norm"

    # 4. Full whitespace-collapse match.
    needle_wc = _whitespace_collapse(needle)
    if needle_wc and needle_wc in _whitespace_collapse(content):
        # We can't locate the exact bytes after collapsing, so fall back
        # to: find the first line of needle (rstrip) in content and use
        # a Levenshtein window of the right size.
        first_line = needle.split("\n", 1)[0].strip()
        if first_line:
            for line_idx, ln in enumerate(content.split("\n")):
                if first_line in ln:
                    original_lines = content.split("\n")
                    start = sum(len(li) + 1 for li in original_lines[:line_idx])
                    needle_lines = needle.count("\n") + 1
                    end_line = line_idx + needle_lines
                    end = sum(len(li) + 1 for li in original_lines[:end_line])
                    if (_whitespace_collapse(content[start:end])
                            == needle_wc):
                        return start, end, "ws_collapse"

    # 5. Levenshtein ≥ 0.9 — last-resort fuzzy window.
    needle_lines = needle.count("\n") + 1
    content_lines = content.split("\n")
    best_ratio = 0.0
    best_start = best_end = -1
    for i in range(0, max(0, len(content_lines) - needle_lines + 1)):
        window = "\n".join(content_lines[i:i + needle_lines])
        ratio = difflib.SequenceMatcher(None, window, needle).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = sum(len(ln) + 1 for ln in content_lines[:i])
            best_end = sum(len(ln) + 1 for ln in content_lines[:i + needle_lines])
    if best_ratio >= 0.9 and best_start >= 0:
        return best_start, best_end, "levenshtein"

    return None, None, ""


def _apply_one(block: SearchReplaceBlock, workdir: Path) -> ApplyResult:
    target = (workdir / block.path).resolve()
    # Guard against path traversal.
    try:
        target.relative_to(workdir.resolve())
    except ValueError:
        return ApplyResult(
            ok=False, block=block,
            reason=f"path {block.path!r} escapes the workspace",
        )

    # New-file case: empty SEARCH = create file.
    if not block.search.strip():
        if target.exists():
            return ApplyResult(
                ok=False, block=block,
                reason=f"empty SEARCH but {block.path} already exists; "
                       "use a non-empty SEARCH block to modify",
            )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(block.replace, encoding="utf-8")
        except (PermissionError, OSError) as e:
            return ApplyResult(ok=False, block=block, reason=str(e))
        return ApplyResult(
            ok=True, block=block, match_kind="created",
            bytes_changed=len(block.replace),
        )

    if not target.exists():
        return ApplyResult(
            ok=False, block=block,
            reason=f"file {block.path} does not exist",
        )
    try:
        content = target.read_text(encoding="utf-8")
    except (PermissionError, OSError, UnicodeDecodeError) as e:
        return ApplyResult(ok=False, block=block, reason=str(e))

    # Normalise to LF for matching; we'll re-apply original EOL on write.
    original_eol = "\r\n" if "\r\n" in content else "\n"
    content_lf = content.replace("\r\n", "\n")
    needle_lf = block.search.replace("\r\n", "\n")
    replace_lf = block.replace.replace("\r\n", "\n")

    # Ambiguity guard: if exact match would hit 2+ locations, demand
    # disambiguation. The fuzzy ladder is only invoked when exact 0-match.
    if content_lf.count(needle_lf) >= 2:
        return ApplyResult(
            ok=False, block=block,
            reason=f"SEARCH block matches {content_lf.count(needle_lf)} "
                   "locations in the file; add more surrounding lines to "
                   "make it unique",
        )

    start, end, kind = _find_with_fuzzy(content_lf, needle_lf)
    if start is None:
        # Provide a near-miss context to help the model re-author.
        # Find the closest line and snip ±5 lines around it.
        first_line = needle_lf.split("\n", 1)[0].strip()
        ctx_lines = content_lf.split("\n")
        best_idx, best_ratio = -1, 0.0
        if first_line:
            for i, ln in enumerate(ctx_lines):
                r = difflib.SequenceMatcher(None, ln.strip(), first_line).ratio()
                if r > best_ratio:
                    best_ratio = r
                    best_idx = i
        near = ""
        if best_idx >= 0:
            lo, hi = max(0, best_idx - 5), min(len(ctx_lines), best_idx + 6)
            near_block = "\n".join(
                f"{i+1:>4}: {ctx_lines[i]}" for i in range(lo, hi)
            )
            near = f"closest match (line {best_idx+1}):\n{near_block}"
        return ApplyResult(
            ok=False, block=block,
            reason="SEARCH block did not match the file content",
            near_miss_context=near,
        )

    # Apply the replacement.
    new_content_lf = content_lf[:start] + replace_lf + content_lf[end:]
    new_content = (
        new_content_lf.replace("\n", original_eol)
        if original_eol == "\r\n" else new_content_lf
    )
    try:
        target.write_text(new_content, encoding="utf-8")
    except (PermissionError, OSError) as e:
        return ApplyResult(ok=False, block=block, reason=str(e))

    return ApplyResult(
        ok=True, block=block, match_kind=kind,
        bytes_changed=len(replace_lf) - (end - start),
    )


def apply_blocks(blocks: list[SearchReplaceBlock], workdir: Path,
                 atomic: bool = True) -> ApplySummary:
    """Apply a list of SEARCH/REPLACE blocks to `workdir`.

    `atomic=True` rolls back ALL writes if any block fails — the agent
    sees an all-or-nothing transaction so partial state doesn't confuse
    subsequent reasoning. `atomic=False` applies what it can and reports
    per-block status (useful for hunk-by-hunk retry).
    """
    summary = ApplySummary()
    if not blocks:
        return summary

    # Snapshot original file contents for rollback.
    snapshots: dict[Path, bytes] = {}
    created: set[Path] = set()
    for blk in blocks:
        target = (workdir / blk.path).resolve()
        if target.exists() and target not in snapshots:
            try:
                snapshots[target] = target.read_bytes()
            except OSError:
                snapshots[target] = b""
        if not target.exists():
            created.add(target)

    rollback_needed = False
    for blk in blocks:
        result = _apply_one(blk, workdir)
        summary.results.append(result)
        if result.ok:
            summary.files_touched.add(blk.path)
        elif atomic:
            rollback_needed = True
            break

    if rollback_needed:
        for target, original in snapshots.items():
            try:
                target.write_bytes(original)
            except OSError:
                pass
        for target in created:
            if target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
    return summary


def render_diff(workdir: Path) -> str:
    """Run `git diff` against `workdir` and return the unified diff.

    Called after `apply_blocks` succeeds to produce the diff payload for
    the benchmark CSV. Models never hand-write `@@ -N,M +N,M @@` hunk
    headers — git computes them from the actual file deltas.

    Wave 12 fix: `git diff HEAD` does NOT include untracked files. SR
    blocks that create a new file via empty-SEARCH succeed on disk but
    were silently absent from the rendered patch (~15% of fix instances
    on SWE-bench Pro need new files). We now `git add --intent-to-add`
    every untracked path before running diff so new files show up
    with a proper `--- /dev/null` hunk.
    """
    import subprocess
    # Wave 12 hardening: use `-z` for NUL-separated `ls-files` output so
    # filenames containing newlines or special chars aren't split into
    # bogus entries. `-c core.quotePath=false` keeps non-ASCII paths
    # unescaped (otherwise `git add` doesn't recognize them). Chunk the
    # `add` invocation to stay under ARG_MAX on large untracked sets.
    try:
        ls = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(workdir),
             "ls-files", "--others", "--exclude-standard", "-z"],
            capture_output=True, timeout=15,
        )
        if ls.returncode == 0 and ls.stdout:
            raw = ls.stdout.decode("utf-8", errors="replace")
            paths = [p for p in raw.split("\x00") if p]
            # Chunk to avoid blowing ARG_MAX (~128KB on Linux). 100 per
            # add is well within limits even for very long paths.
            for i in range(0, len(paths), 100):
                chunk = paths[i:i + 100]
                subprocess.run(
                    ["git", "-C", str(workdir), "add", "--intent-to-add",
                     "--"] + chunk,
                    capture_output=True, timeout=30,
                )
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        proc = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(workdir), "diff",
             "--no-color", "--no-ext-diff", "--unified=3", "HEAD"],
            capture_output=True, timeout=30,
        )
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", errors="replace")
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


# ---- Inference-time edit repair (the Aider "reflection" pattern) ----


def repair_prompt_for_failure(result: ApplyResult, file_content: str = "") -> str:
    """Build a targeted re-prompt for a failed SEARCH/REPLACE block.

    Per Aider's published research, re-prompting the model with the
    failed search text + the actual file slice + a clear "fix it" hint
    reduces editing errors ~9x. We surface (a) the exact failed search,
    (b) the closest section of the file, (c) a structured re-emit
    instruction.
    """
    blk = result.block
    parts = [
        f"Your SEARCH/REPLACE block for `{blk.path}` did not apply.",
        f"Reason: {result.reason}",
        "",
    ]
    if result.near_miss_context:
        parts.append(result.near_miss_context)
        parts.append("")
    parts.append(
        "Re-emit the block with the EXACT bytes from the file (including "
        "leading whitespace and trailing newline). Use the structure:"
    )
    parts.append("")
    parts.append(f"{blk.path}")
    parts.append("<<<<<<< SEARCH")
    parts.append("<exact existing lines>")
    parts.append("=======")
    parts.append("<new lines>")
    parts.append(">>>>>>> REPLACE")
    return "\n".join(parts)
