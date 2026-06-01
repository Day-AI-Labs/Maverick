"""WorldModel locked read helpers + status-vocab reconciliation (#470).

Covers the new locked helpers (kv_memory / recall / monitor now route
through them instead of raw conn.execute) and that recall/monitor query the
status vocabulary the kernel actually writes (done/blocked/active), not the
never-written 'succeeded'/'failed'/'in_progress'.
"""
from __future__ import annotations

from pathlib import Path

from maverick.world_model import WorldModel


def _world(tmp_path: Path) -> WorldModel:
    return WorldModel(tmp_path / "w.db")


class TestLockedFactHelpers:
    def test_set_get_delete_roundtrip(self, tmp_path):
        w = _world(tmp_path)
        w.set_fact_raw("goal:1:color", "blue")
        assert w.get_fact("goal:1:color") == "blue"
        # Upsert overwrites.
        w.set_fact_raw("goal:1:color", "green")
        assert w.get_fact("goal:1:color") == "green"
        assert w.delete_fact("goal:1:color") == 1
        assert w.get_fact("goal:1:color") is None
        w.close()

    def test_list_and_search_scoped(self, tmp_path):
        w = _world(tmp_path)
        w.set_fact_raw("goal:1:a", "apple")
        w.set_fact_raw("goal:1:b", "banana")
        w.set_fact_raw("goal:2:c", "cherry")  # different goal scope
        listed = w.list_facts("goal:1:%")
        keys = {k for k, _ in listed}
        assert keys == {"goal:1:a", "goal:1:b"}  # goal 2 excluded
        hits = w.search_facts("goal:1:%", "%ana%")
        assert hits == [("goal:1:b", "banana")]
        w.close()


class TestStatusReconciliation:
    def _seed(self, w):
        import time
        rows = [
            (1, "done auth", "done"),
            (2, "blocked deadlock", "blocked"),
            (3, "running migration", "active"),
            (4, "queued task", "pending"),
            (5, "cancelled thing", "cancelled"),
        ]
        now = time.time()
        for gid, title, status in rows:
            w.conn.execute(
                "INSERT INTO goals(id, title, description, status, "
                "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (gid, title, "desc", status, now - gid, now - gid),
            )
        w.conn.commit()

    def test_candidate_goals_finished_only(self, tmp_path):
        w = _world(tmp_path)
        self._seed(w)
        finished = {g.status for g in w.candidate_goals(include_running=False)}
        # done/blocked/cancelled are finished; active/pending excluded.
        assert finished == {"done", "blocked", "cancelled"}
        w.close()

    def test_candidate_goals_include_running(self, tmp_path):
        w = _world(tmp_path)
        self._seed(w)
        all_statuses = {g.status for g in w.candidate_goals(include_running=True)}
        assert "active" in all_statuses and "pending" in all_statuses
        w.close()

    def test_resolve_active_prefers_active_over_terminal(self, tmp_path):
        w = _world(tmp_path)
        self._seed(w)
        # #3 (active) and #4 (pending) are the live ones; #3 is newer.
        g = w.resolve_active_goal()
        assert g is not None
        assert g.status in ("active", "pending")
        assert g.id == 3  # newest non-terminal

    def test_resolve_active_falls_back_when_none_live(self, tmp_path):
        w = _world(tmp_path)
        import time
        w.conn.execute(
            "INSERT INTO goals(id, title, description, status, created_at, "
            "updated_at) VALUES(?, ?, ?, ?, ?, ?)",
            (1, "only a done goal", "d", "done", time.time(), time.time()),
        )
        w.conn.commit()
        g = w.resolve_active_goal()
        assert g is not None and g.id == 1  # any-status fallback
        w.close()


class TestReadHelpersLocked:
    def test_read_all_and_one(self, tmp_path):
        w = _world(tmp_path)
        w.create_goal("a", "x")
        w.create_goal("b", "y")
        rows = w._read_all("SELECT id FROM goals ORDER BY id")
        assert [r["id"] for r in rows] == [1, 2]
        one = w._read_one("SELECT title FROM goals WHERE id=?", (2,))
        assert one["title"] == "b"
        assert w._read_one("SELECT * FROM goals WHERE id=?", (999,)) is None
        w.close()
