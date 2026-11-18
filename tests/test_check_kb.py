import json
import os
import re
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "skill", "scripts"))
sys.path.insert(0, _HERE)
import kblib
from _fixtures import make_repo, run_script
from shutil import which

HAS_GIT = which("git") is not None


class CheckKbTestBase(unittest.TestCase):
    def setUp(self):
        if not HAS_GIT:
            self.skipTest("git not installed")
        self.tmp = tempfile.mkdtemp()
        make_repo(self.tmp, files={"README.md": "hello\n"})
        r = run_script("kb_init.py", "--project", self.tmp, "--systems", "api", cwd=self.tmp)
        assert r.returncode == 0, r.stderr
        self.kb = os.path.join(self.tmp, "mighty-ops")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self, *args):
        return run_script("check_kb.py", "--project", self.tmp, *args, cwd=self.tmp)

    def load_state(self):
        with open(os.path.join(self.kb, "state.json")) as f:
            return json.load(f)

    def save_state(self, st):
        with open(os.path.join(self.kb, "state.json"), "w") as f:
            json.dump(st, f, indent=2)

    def write(self, rel, content):
        full = os.path.join(self.kb, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)


class TestCleanKb(CheckKbTestBase):
    def test_fresh_kb_is_clean(self):
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 errors", r.stdout)


class TestErrorCodes(CheckKbTestBase):
    def test_e01_missing_state(self):
        os.remove(os.path.join(self.kb, "state.json"))
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E01", r.stdout)

    def test_e01_invalid_json(self):
        with open(os.path.join(self.kb, "state.json"), "w") as f:
            f.write("{not json")
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E01", r.stdout)

    def test_e02_bad_schema(self):
        st = self.load_state()
        st["schema"] = "other/1"
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E02", r.stdout)

    def test_e02_missing_key(self):
        st = self.load_state()
        del st["counters"]
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E02", r.stdout)

    def test_e03_system_folder_missing(self):
        shutil.rmtree(os.path.join(self.kb, "systems", "api"))
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E03", r.stdout)

    def test_e04_required_file_missing(self):
        os.remove(os.path.join(self.kb, "systems", "api", "limitations.md"))
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E04", r.stdout)

    def test_e05_dr_missing_date(self):
        self.write(
            os.path.join("decisions", "DR-0001-x.md"),
            "# DR-0001 - x\n- Status: proposed\n## Reason\nbecause\n",
        )
        st = self.load_state()
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E05", r.stdout)

    def test_e05_dr_bad_status(self):
        self.write(
            os.path.join("decisions", "DR-0001-x.md"),
            "# DR-0001 - x\n- Date: 2026-01-01\n- Status: whatever\n## Reason\nbecause\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E05", r.stdout)

    def test_e05_dr_empty_reason(self):
        self.write(
            os.path.join("decisions", "DR-0001-x.md"),
            "# DR-0001 - x\n- Date: 2026-01-01\n- Status: proposed\n## Reason\n\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E05", r.stdout)

    def test_e06_unknown_commit(self):
        st = self.load_state()
        st["last_synced_commit"] = "f" * 40
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E06", r.stdout)

    def test_e07_entry_count_regression(self):
        self.write(
            os.path.join("systems", "api", "limitations.md"),
            "# api - limitations\nUpdated: 2026-01-01\n"
            "### L-1 — one\n- Since: 2026-01-01\n- Status: open\n- Evidence: x\ntext\n",
        )
        r = self.check("--record")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.write(
            os.path.join("systems", "api", "limitations.md"),
            "# api - limitations\nUpdated: 2026-01-01\n(none recorded yet)\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E07", r.stdout)

    def test_e08_duplicate_entry_id(self):
        self.write(
            os.path.join("systems", "api", "limitations.md"),
            "# api - limitations\nUpdated: 2026-01-01\n"
            "### L-1 — one\n- Since: 2026-01-01\n- Status: open\n- Evidence: x\ntext\n"
            "### L-1 — dup\n- Since: 2026-01-01\n- Status: open\n- Evidence: y\ntext\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E08", r.stdout)

    def test_e09_dangling_dr_link(self):
        self.write(
            os.path.join("systems", "api", "decisions.md"),
            "# api - decisions\nUpdated: 2026-01-01\n"
            "- DR-0099 (2026-01-01, accepted) — title -> ../../decisions/DR-0099-title.md\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E09", r.stdout)

    def test_e10_secret_like_content(self):
        self.write(
            os.path.join("systems", "api", "findings.md"),
            "# api - findings\nUpdated: 2026-01-01\nkey: AKIAABCDEFGHIJKLMNOP\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E10", r.stdout)

    def test_e10_luhn_does_not_flag_non_luhn_16_digit(self):
        # 1234567812345678 fails the Luhn check (not a valid card number).
        self.write(
            os.path.join("systems", "api", "findings.md"),
            "# api - findings\nUpdated: 2026-01-01\nid: 1234567812345678\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("E10", r.stdout)

    def test_e11_bad_enum_value(self):
        st = self.load_state()
        st["systems"][0]["kind"] = "bogus"
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E11", r.stdout)

    def test_e12_systems_done_not_subset(self):
        st = self.load_state()
        st["pending_sync"] = {
            "from": "a",
            "to": "b",
            "created_at": kblib.now_iso(),
            "systems": ["api"],
            "systems_done": ["api", "ghost"],
            "digest": "digests/catchup-x.md",
            "regression_flags": [],
        }
        self.save_state(st)
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E12", r.stdout)


class TestWarnings(CheckKbTestBase):
    def test_w01_orphan_folder(self):
        os.makedirs(os.path.join(self.kb, "systems", "ghost"))
        for fname in kblib.REQUIRED_FILES:
            self.write(os.path.join("systems", "ghost", fname), "# ghost\nUpdated: 2026-01-01\n(none recorded yet)\n")
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("W01", r.stdout)

    def test_w03_stale_inbox(self):
        self.write(
            os.path.join("inbox", "human.md"),
            "# Brief\n- Written: 2000-01-01T00:00:00Z by someone\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("W03", r.stdout)

    def test_w04_long_file(self):
        self.write(
            os.path.join("systems", "api", "findings.md"),
            "# api - findings\nUpdated: 2026-01-01\n" + ("line\n" * 450),
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("W04", r.stdout)

    def test_strict_turns_warnings_to_exit_1(self):
        self.write(
            os.path.join("inbox", "human.md"),
            "# Brief\n- Written: 2000-01-01T00:00:00Z by someone\n",
        )
        r = self.check("--strict")
        self.assertEqual(r.returncode, 1)


class TestRecord(CheckKbTestBase):
    def test_record_then_deleting_entry_gives_e07(self):
        self.write(
            os.path.join("systems", "api", "todo.md"),
            "# api - todo\nUpdated: 2026-01-01\n"
            "### T-1 — one\n- Since: 2026-01-01\n- Status: open\n- Evidence: x\ntext\n"
            "### T-2 — two\n- Since: 2026-01-01\n- Status: open\n- Evidence: y\ntext\n",
        )
        r = self.check("--record")
        self.assertEqual(r.returncode, 0, r.stdout)
        st = self.load_state()
        self.assertEqual(st["systems"][0]["counts"]["todo"], 2)

        self.write(
            os.path.join("systems", "api", "todo.md"),
            "# api - todo\nUpdated: 2026-01-01\n"
            "### T-1 — one\n- Since: 2026-01-01\n- Status: open\n- Evidence: x\ntext\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E07", r.stdout)

    def test_superseding_entry_kept_still_clean(self):
        self.write(
            os.path.join("systems", "api", "todo.md"),
            "# api - todo\nUpdated: 2026-01-01\n"
            "### T-1 — one\n- Since: 2026-01-01\n- Status: open\n- Evidence: x\ntext\n",
        )
        r = self.check("--record")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.write(
            os.path.join("systems", "api", "todo.md"),
            "# api - todo\nUpdated: 2026-01-02\n"
            "### T-1 — one\n- Since: 2026-01-01\n"
            "- Status: superseded by T-2 (2026-01-02: reason)\n- Evidence: x\ntext\n"
            "### T-2 — two\n- Since: 2026-01-02\n- Status: open\n- Evidence: y\ntext\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "check_kb: 0 errors, 0 warnings (1 systems, 0 DRs)")

    def test_p4_01_item9_record_counts_dr_index_lines(self):
        self.write(
            os.path.join("decisions", "DR-0001-map.md"),
            "# DR-0001 — map\n- Date: 2026-01-01\n- Status: accepted\n## Reason\nbecause\n",
        )
        self.write(
            os.path.join("decisions", "DR-0002-two.md"),
            "# DR-0002 — two\n- Date: 2026-01-01\n- Status: accepted\n## Reason\nbecause\n",
        )
        index = (
            "# api - decisions\nUpdated: 2026-01-01\n"
            "- DR-0001 (2026-01-01, accepted) — map → ../../decisions/DR-0001-map.md\n"
            "- DR-0002 (2026-01-01, accepted) — two → ../../decisions/DR-0002-two.md\n"
        )
        self.write(os.path.join("systems", "api", "decisions.md"), index)
        r = self.check("--record")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.load_state()["systems"][0]["counts"]["decisions"], 2)
        # A status change appends a second line for the same DR: still 2, no E08.
        self.write(
            os.path.join("systems", "api", "decisions.md"),
            index + "- DR-0002 (2026-01-02, rejected) — two → ../../decisions/DR-0002-two.md\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        # Deleting an index line is now caught by E07.
        self.write(
            os.path.join("systems", "api", "decisions.md"),
            "# api - decisions\nUpdated: 2026-01-01\n"
            "- DR-0001 (2026-01-01, accepted) — map → ../../decisions/DR-0001-map.md\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("E07", r.stdout)


class TestP403SecretSlug(CheckKbTestBase):
    def test_p4_03_item2_e10_ignores_kebab_slug_containing_sk(self):
        self.write(
            os.path.join("exchanges", "EX-20261024-001-ask-which-file-owns-the-worker.md"),
            "# EX-20261024-001\nRecord: exchanges/EX-20261024-001-ask-which-file-owns-the-worker.md\n"
            "also task-runner-configuration-loader-module and disk-usage-reporting-tool-for-teams\n",
        )
        r = self.check()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("E10", r.stdout)

    def test_p4_03_item2_e10_still_flags_real_key_shapes(self):
        for text in ("key=sk-abcdefghijklmnopqrstuvwx12", "`sk-proj-AbCdEfGhIjKlMnOpQrStUv12`",
                     "token: sk-ABCDEFGHIJKLMNOPQRSTUVWX"):
            self.write(os.path.join("systems", "api", "findings.md"),
                       "# api - findings\nUpdated: 2026-01-01\n%s\n" % text)
            r = self.check()
            self.assertEqual(r.returncode, 1, text)
            self.assertIn("api-key", r.stdout, text)


class TestJsonAndMisc(CheckKbTestBase):
    def test_json_shape(self):
        r = self.check("--json")
        self.assertEqual(r.returncode, 0, r.stdout)
        data = json.loads(r.stdout)
        self.assertIn("errors", data)
        self.assertIn("warnings", data)
        self.assertIn("systems", data)
        self.assertIn("drs", data)

    def test_no_kb_exits_2(self):
        empty = tempfile.mkdtemp()
        try:
            r = run_script("check_kb.py", "--project", empty, cwd=empty)
            self.assertEqual(r.returncode, 2)
        finally:
            shutil.rmtree(empty, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
