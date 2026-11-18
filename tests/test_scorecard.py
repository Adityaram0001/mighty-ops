"""Tests for scripts/scorecard.py."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixtures as fx


def run_json(cost, subtype="success", denials=0):
    return json.dumps({
        "total_cost_usd": cost, "subtype": subtype, "num_turns": 5,
        "terminal_reason": "max_turns" if subtype == "error_max_turns" else "completed",
        "permission_denials": [{"tool_name": "Bash"}] * denials,
    })


def exchange(mode, prov):
    return "# EX-1 — %s — x\n- Mode: %s\n- KB at: %s (provisional: %s)\n" % (
        mode, mode, "a" * 40, prov)


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = os.path.join(self._td.name, "proj")
        self.files = {
            "orchestration/workers/a-01/run.json": run_json(1.0, denials=2),
            "orchestration/workers/a-01/result.md": "STATUS: DONE\n",
            "orchestration/workers/a-01/spawns.log": "## spawn t role=explore model=opus max_turns=9 resume=0\n",
            "orchestration/workers/b-01/run.json": run_json(3.0),
            "orchestration/workers/b-01/result.md": "STATUS: BLOCKED\n",
            "orchestration/workers/b-01/spawns.log": "## spawn t role=build model=opus max_turns=9 resume=0\n",
            "orchestration/workers/c-01/run.json": run_json(2.0),
            "orchestration/workers/c-01/run.111.json": run_json(1.0, "error_max_turns"),
            "orchestration/workers/c-01/result.md": "STATUS: DONE\n",
            "orchestration/plan.md": "# plan\n## Re-plans (append, dated)\n- 2026-10-24 01:00: x\n- 2026-10-23 01:00: y\n\n## Phase 6\n- 2026-10-24 other\n",
            "orchestration/questions.md": "# q\n### Q1 (d) from m — OPEN\nQuestion:\n### Q2 (d) from m — ANSWERED\n",
            "tests/test_x.py": "def test_a(): pass\n    def test_b(): pass\n",
            "src/test_y.py": "def test_c(): pass\n",
            "src/app.py": "x = 1\n",
        }
        fx.make_repo(self.root, self.files)

    def kb(self, exchanges=()):
        kb = os.path.join(self.root, "mighty-ops")
        os.makedirs(os.path.join(kb, "exchanges"))
        with open(os.path.join(kb, "state.json"), "w") as f:
            json.dump({"schema": "mighty-ops-kb/1", "systems": [
                {"id": "t", "tests": ["tests"]}]}, f)
        for i, (mode, prov) in enumerate(exchanges):
            with open(os.path.join(kb, "exchanges", "EX-%d.md" % i), "w") as f:
                f.write(exchange(mode, prov))
        return kb

    def metrics(self, *extra):
        r = fx.run_script("scorecard.py", "--project", self.root, "--json", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        return {m["key"]: m for m in d["metrics"]}

    def test_no_orchestration_exits_2(self):
        empty = fx.make_repo(os.path.join(self._td.name, "e"), {"a.txt": "x"})
        r = fx.run_script("scorecard.py", "--project", empty)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)

    def test_no_kb_prints_only(self):
        r = fx.run_script("scorecard.py", "--project", self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| metric | value | source |", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.root, "mighty-ops")))
        self.assertIn("n/a (no KB)", r.stdout)

    def test_json_shape_at_most_8_metrics(self):
        m = self.metrics()
        self.assertLessEqual(len(m), 8)
        for rec in m.values():
            self.assertEqual(set(rec), {"key", "metric", "value", "source", "data"})
            self.assertTrue(rec["source"])

    def test_units_cost_sums_resumed_runs(self):
        d = self.metrics()["units_cost"]["data"]
        self.assertEqual(d["units"], 3)
        self.assertAlmostEqual(d["cost_usd"], 7.0)

    def test_resume_detection(self):
        self.assertEqual(self.metrics()["resumed"]["data"]["count"], 1)

    def test_explore_share(self):
        self.assertAlmostEqual(self.metrics()["units_cost"]["data"]["explore_percent"], 25.0, places=1)

    def test_stalled_and_denials(self):
        m = self.metrics()
        self.assertEqual(m["stalled"]["data"], {"MAX_TURNS": 1, "BLOCKED": 1, "FAILED": 0, "total": 2})
        self.assertEqual(m["denials"]["data"]["count"], 2)

    def test_questions_and_replans(self):
        m = self.metrics()
        self.assertEqual(m["questions"]["data"], {"total": 2, "open": 1, "answered": 1})
        self.assertEqual(m["replans"]["data"]["count"], 2)

    def test_questions_absent(self):
        os.remove(os.path.join(self.root, "orchestration", "questions.md"))
        self.assertIsNone(self.metrics()["questions"]["data"]["total"])

    def test_test_count_repo_wide_fallback(self):
        fx._git(self.root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                "commit", "--allow-empty", "-q", "-m", "e")
        self.assertEqual(self.metrics()["tests"]["data"]["count"], 3)

    def test_test_count_uses_state_paths(self):
        self.kb()
        self.assertEqual(self.metrics("--kb", "mighty-ops")["tests"]["data"]["count"], 2)

    def test_provisional_share(self):
        self.kb([("decide", "yes"), ("decide", "no"), ("ask", "yes")])
        d = self.metrics("--kb", "mighty-ops")["decide"]["data"]
        self.assertEqual(d, {"calls": 2, "provisional": 1})

    def test_history_is_append_only(self):
        kb = self.kb()
        for _ in range(2):
            r = fx.run_script("scorecard.py", "--project", self.root, "--kb", "mighty-ops")
            self.assertEqual(r.returncode, 0, r.stderr)
            if _ == 0:
                with open(os.path.join(kb, "scorecard.md")) as f:
                    first = f.read()
        with open(os.path.join(kb, "scorecard.md")) as f:
            second = f.read()
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.splitlines()), len(first.splitlines()) + 1)
        self.assertTrue(first.startswith("# Scorecard history"))
        digests = os.listdir(os.path.join(kb, "digests"))
        self.assertTrue(any(n.startswith("scorecard-") for n in digests))

    def test_out_writes_report(self):
        out = os.path.join(self._td.name, "r.md")
        r = fx.run_script("scorecard.py", "--project", self.root, "--out", out)
        self.assertEqual(r.returncode, 0)
        with open(out) as f:
            self.assertIn("| metric | value | source |", f.read())


if __name__ == "__main__":
    unittest.main()
