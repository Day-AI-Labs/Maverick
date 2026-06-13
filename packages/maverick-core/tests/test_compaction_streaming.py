"""Streaming compaction (v7): running summary + cursor, folding only new turns."""
from __future__ import annotations

import json
import os
import re
import stat
from types import SimpleNamespace

from maverick.compaction_streaming import (
    StreamingCompactor,
    _default_key,
    compact_streaming,
)


def _section(blob: str, tag: str) -> str:
    m = re.search(rf"<{tag}>\n?(.*?)\n?</{tag}>", blob, re.S)
    return m.group(1) if m else ""


class ConcatLLM:
    """Fold-by-concatenation fake: summary' = summary lines + new-turn lines."""

    def __init__(self):
        self.calls: list[dict] = []

    def complete(self, system, messages, tools=None, budget=None,
                 max_tokens=4096, thinking_budget=None, model=None):
        blob = messages[0]["content"]
        self.calls.append({"system": system, "content": blob, "model": model})
        lines = [
            ln for ln in (
                _section(blob, "summary") + "\n" + _section(blob, "new-turns")
            ).splitlines() if ln.strip()
        ]
        return SimpleNamespace(text="\n".join(lines))


def _turns(n: int) -> list[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"FACT_{i} noted"}
        for i in range(n)
    ]


class TestFold:
    def test_streaming_equals_batch(self, tmp_path):
        turns = _turns(9)
        batch = StreamingCompactor(llm=ConcatLLM(), path=tmp_path / "a.json")
        batch_summary = batch.fold("conv", turns)

        inc = StreamingCompactor(llm=ConcatLLM(), path=tmp_path / "b.json")
        inc.fold("conv", turns[:3])
        inc.fold("conv", turns[:6])
        inc_summary = inc.fold("conv", turns)

        batch_facts = {ln for ln in batch_summary.splitlines() if "FACT_" in ln}
        inc_facts = {ln for ln in inc_summary.splitlines() if "FACT_" in ln}
        assert batch_facts == inc_facts
        for i in range(9):
            assert f"FACT_{i}" in inc_summary

    def test_only_new_turns_are_folded(self, tmp_path):
        llm = ConcatLLM()
        sc = StreamingCompactor(llm=llm, path=tmp_path / "s.json")
        sc.fold("conv", _turns(3))
        sc.fold("conv", _turns(6))
        assert len(llm.calls) == 2
        second_new = _section(llm.calls[1]["content"], "new-turns")
        assert "FACT_3" in second_new and "FACT_5" in second_new
        assert "FACT_0" not in second_new  # already in the running summary
        assert "FACT_0" in _section(llm.calls[1]["content"], "summary")

    def test_no_new_turns_is_a_no_llm_call(self, tmp_path):
        llm = ConcatLLM()
        sc = StreamingCompactor(llm=llm, path=tmp_path / "s.json")
        first = sc.fold("conv", _turns(4))
        again = sc.fold("conv", _turns(4))
        assert again == first
        assert len(llm.calls) == 1

    def test_cursor_persists_across_instances(self, tmp_path):
        path = tmp_path / "s.json"
        StreamingCompactor(llm=ConcatLLM(), path=path).fold("conv", _turns(3))
        sc2 = StreamingCompactor(llm=ConcatLLM(), path=path)
        assert sc2.state("conv")[0] == 3
        summary = sc2.fold("conv", _turns(5))
        assert "FACT_4" in summary and "FACT_0" in summary

    def test_rewound_conversation_resets_and_refolds(self, tmp_path):
        sc = StreamingCompactor(llm=ConcatLLM(), path=tmp_path / "s.json")
        sc.fold("conv", _turns(5))
        summary = sc.fold("conv", _turns(2))  # shorter than cursor: rewind
        assert "FACT_1" in summary
        assert "FACT_4" not in summary
        assert sc.state("conv")[0] == 2

    def test_prefix_mismatch_resets_state_for_same_key(self, tmp_path):
        llm = ConcatLLM()
        sc = StreamingCompactor(llm=llm, path=tmp_path / "s.json")
        sc.fold("shared", [
            {"role": "user", "content": "SECRET_A_PAYROLL"},
            {"role": "assistant", "content": "A result"},
        ])

        summary = sc.fold("shared", [
            {"role": "user", "content": "B public data"},
            {"role": "assistant", "content": "B result"},
        ])

        assert "SECRET_A_PAYROLL" not in summary
        assert "B public data" in summary
        assert len(llm.calls) == 2
        assert "SECRET_A_PAYROLL" not in _section(llm.calls[1]["content"], "summary")

    def test_legacy_state_without_fingerprint_resets(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text(json.dumps({
            "conv": {"cursor": 1, "summary": "SECRET_LEGACY", "last": 1.0},
        }), encoding="utf-8")

        summary = StreamingCompactor(path=path).fold(
            "conv", [{"role": "user", "content": "fresh fact"}],
        )

        assert "SECRET_LEGACY" not in summary
        assert "fresh fact" in summary

    def test_heuristic_fold_without_llm_is_deterministic(self, tmp_path):
        sc = StreamingCompactor(path=tmp_path / "s.json")
        summary = sc.fold("conv", _turns(2))
        assert summary == "user: FACT_0 noted\nassistant: FACT_1 noted"

    def test_llm_error_degrades_to_heuristic_fold(self, tmp_path):
        class Boom:
            def complete(self, *a, **kw):
                raise RuntimeError("api down")

        sc = StreamingCompactor(llm=Boom(), path=tmp_path / "s.json")
        assert "FACT_0" in sc.fold("conv", _turns(1))

    def test_uses_configured_summarizer_role_model(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MAVERICK_MODEL_OVERRIDE_SUMMARIZER", "testprov:tiny-sum")
        llm = ConcatLLM()
        StreamingCompactor(llm=llm, path=tmp_path / "s.json").fold("conv", _turns(1))
        assert llm.calls[0]["model"] == "testprov:tiny-sum"

    def test_sidecar_owner_only_and_injected_clock(self, tmp_path):
        path = tmp_path / "s.json"
        sc = StreamingCompactor(path=path, clock=lambda: 99.0)
        sc.fold("conv", _turns(1))
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert raw["conv"]["cursor"] == 1
        assert raw["conv"]["last"] == 99.0
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_reset_clears_conversation_state(self, tmp_path):
        sc = StreamingCompactor(path=tmp_path / "s.json")
        sc.fold("conv", _turns(3))
        sc.reset("conv")
        assert sc.state("conv") == (0, "")


class TestFolderCoroutine:
    def test_send_new_turns_yields_running_summary(self, tmp_path):
        sc = StreamingCompactor(llm=ConcatLLM(), path=tmp_path / "s.json")
        gen = sc.folder("conv")
        assert next(gen) == ""  # primed: empty summary
        summary = gen.send(_turns(2))
        assert "FACT_0" in summary and "FACT_1" in summary
        summary = gen.send([{"role": "user", "content": "FACT_9 noted"}])
        assert "FACT_9" in summary and "FACT_0" in summary
        assert sc.state("conv")[0] == 3  # cursor advanced and persisted

    def test_send_nothing_repeats_summary(self, tmp_path):
        sc = StreamingCompactor(path=tmp_path / "s.json")
        gen = sc.folder("conv")
        next(gen)
        first = gen.send(_turns(1))
        assert gen.send([]) == first


class TestCompactStreamingStrategy:
    def _msgs(self, n_mid: int) -> list[dict]:
        return (
            [{"role": "user", "content": "GOAL: the brief."}]
            + _turns(n_mid)
            + [{"role": "user", "content": "recent q"},
               {"role": "assistant", "content": "recent a"}]
        )

    def test_short_list_passes_through(self, tmp_path):
        msgs = [{"role": "user", "content": "hi"}]
        assert compact_streaming(msgs, path=tmp_path / "s.json") == msgs

    def test_middle_replaced_by_stream_summary(self, tmp_path):
        msgs = self._msgs(6)
        out = compact_streaming(
            msgs, conversation_id="c1", keep_recent=2,
            llm=ConcatLLM(), path=tmp_path / "s.json",
        )
        assert out[0] == msgs[0]
        assert out[-2:] == msgs[-2:]
        assert len(out) == 4  # brief + summary + 2-message tail
        assert '<stream-summary turns="6">' in out[1]["content"]
        assert "FACT_5" in out[1]["content"]

    def test_second_compaction_folds_only_the_delta(self, tmp_path):
        llm = ConcatLLM()
        msgs = self._msgs(6)
        compact_streaming(msgs, conversation_id="c1", keep_recent=2,
                          llm=llm, path=tmp_path / "s.json")
        grown = self._msgs(6) + [
            {"role": "user", "content": "FACT_77 noted"},
            {"role": "assistant", "content": "FACT_78 noted"},
        ]
        out = compact_streaming(grown, conversation_id="c1", keep_recent=2,
                                llm=llm, path=tmp_path / "s.json")
        assert len(llm.calls) == 2
        second_new = _section(llm.calls[1]["content"], "new-turns")
        assert "recent q" in second_new          # the old tail aged into the fold
        assert "FACT_5" not in second_new        # already summarized
        assert "FACT_5" in out[1]["content"]     # but still in the running summary

    def test_default_key_collision_does_not_reuse_other_prefix(self, tmp_path):
        a = (
            [{"role": "user", "content": "summarize my file"}]
            + [
                {"role": "user", "content": "SECRET_A_PAYROLL"},
                {"role": "assistant", "content": "A analysis"},
                {"role": "user", "content": "A followup"},
            ]
            + [{"role": "user", "content": "recent q"}]
        )
        b = (
            [{"role": "user", "content": "summarize my file"}]
            + [
                {"role": "user", "content": "B harmless"},
                {"role": "assistant", "content": "B analysis"},
                {"role": "user", "content": "B followup"},
            ]
            + [{"role": "user", "content": "recent q"}]
        )
        path = tmp_path / "s.json"

        compact_streaming(a, keep_recent=1, llm=ConcatLLM(), path=path)
        out = compact_streaming(b, keep_recent=1, llm=ConcatLLM(), path=path)

        assert _default_key(a) == _default_key(b)
        assert "SECRET_A_PAYROLL" not in out[1]["content"]
        assert "B harmless" in out[1]["content"]

    def test_default_key_stable_per_first_message(self):
        a = [{"role": "user", "content": "brief"}, {"role": "user", "content": "x"}]
        b = [{"role": "user", "content": "brief"}, {"role": "user", "content": "y"}]
        c = [{"role": "user", "content": "other brief"}]
        assert _default_key(a) == _default_key(b)
        assert _default_key(a) != _default_key(c)
