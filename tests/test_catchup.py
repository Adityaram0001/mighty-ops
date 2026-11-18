import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from shutil import which

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "skill", "scripts"))
sys.path.insert(0, _HERE)
import kblib
from _fixtures import make_repo, run_script, write_files

HAS_GIT = which("git") is not None


def git_raw(repo, *args):
    return subprocess.run(
        ["git"] + list(args), cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )


def git_sha(repo, rev="HEAD"):
    return git_raw(repo, "rev-parse", rev).stdout.strip()


def make_system(id_, paths, tests=None, kind="feature"):
    return {
        "id": id_, "name": id_, "kind": kind, "paths": paths, "tests": tests or [],
        "status": "active", "superseded_by": [], "derived_from": [],
        "health": "unknown", "health_reason": "", "last_changed_commit": None,
        "updated_at": "2026-01-01T00:00:00Z",
        "counts": {"findings": 0, "limitations": 0, "todo": 0, "done": 0, "decisions": 0},
    }


@unittest.skipUnless(HAS_GIT, "git not installed")
class CatchupTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_state(self, systems, last_synced_commit=None, pending_sync=None,
                     noise_paths=None, first_run=None):
        kb = os.path.join(self.tmp, "mighty-ops")
        os.makedirs(kb, exist_ok=True)
        st = {
            "schema": kblib.SCHEMA,
            "kb_dir": "mighty-ops",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "commit_policy": "auto",
            "last_synced_commit": last_synced_commit,
            "last_synced_at": None,
            "pending_sync": pending_sync,
            "first_run": first_run or {
                "status": "done", "head": last_synced_commit, "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "2026-01-01T00:00:00Z", "passes_done": [],
            },
            "noise_paths": noise_paths if noise_paths is not None else ["orchestration/"],
            "systems": systems,
            "health": {"overall": "unknown", "kb_check": "unknown", "checked_at": None},
            "counters": {"dr": 0, "exchange_seq": {}, "brief_seq": {}},
        }
        with open(os.path.join(kb, "state.json"), "w", encoding="utf-8") as f:
            json.dump(st, f)
        return kb

    def load_state(self):
        with open(os.path.join(self.tmp, "mighty-ops", "state.json")) as f:
            return json.load(f)

    def run_catchup(self, *args):
        return run_script("catchup.py", *(["--project", self.tmp] + list(args)), cwd=self.tmp)

    def run_json(self, *args):
        r = self.run_catchup("--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)


class TestUpToDate(CatchupTestBase):
    def test_up_to_date_when_no_commits(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([], last_synced_commit=sha0)
        data = self.run_json()
        self.assertEqual(data["status"], "up_to_date")
        self.assertEqual(data["commits"], 0)
        st = self.load_state()
        self.assertEqual(st["last_synced_commit"], sha0)
        self.assertIsNone(st["pending_sync"])


class TestGrouping(CatchupTestBase):
    def test_groups_by_longest_prefix(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n", "src/core.py": "1\n"})
        sha0 = git_sha(self.tmp)
        write_files(self.tmp, {"src/api/x.py": "2\n", "src/core.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change")
        self.write_state(
            [make_system("api", ["src/api/"]), make_system("core", ["src/"])],
            last_synced_commit=sha0,
        )
        data = self.run_json()
        by_id = {s["id"]: s for s in data["systems"]}
        self.assertIn("api", by_id)
        self.assertIn("core", by_id)
        api_paths = {f["path"] for f in by_id["api"]["files"]}
        core_paths = {f["path"] for f in by_id["core"]["files"]}
        self.assertIn("src/api/x.py", api_paths)
        self.assertNotIn("src/api/x.py", core_paths)
        self.assertIn("src/core.py", core_paths)


class TestOrchestrationSeparatedAndKbExcluded(CatchupTestBase):
    def test_orchestration_separated_and_kb_only_commits_excluded(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/api/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"mighty-ops/note.md": "kb only\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "kb commit")
        write_files(self.tmp, {"orchestration/plan.md": "# plan\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "orch commit")
        write_files(self.tmp, {"src/api/x.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "real change")
        data = self.run_json()
        self.assertEqual(data["commits"], 1)
        self.assertEqual(data["commits_total"], 3)
        self.assertTrue(data["orchestration"]["plan_changed"])
        self.assertGreater(data["orchestration"]["files"], 0)
        blob = json.dumps(data)
        self.assertNotIn("mighty-ops/note.md", blob)


class TestUnmappedNewCandidate(CatchupTestBase):
    def test_unmapped_path_and_new_system_candidate(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/api/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"newdir/newfile.py": "1\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "new dir")
        data = self.run_json()
        self.assertIn("newdir/newfile.py", data["unmapped"])
        self.assertIn("newdir", data["new_system_candidates"])


class TestRegressionFlags(CatchupTestBase):
    def test_test_fn_drop_flagged(self):
        make_repo(self.tmp, files={
            "tests/test_x.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n",
        })
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/"], tests=["tests/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"tests/test_x.py": "def test_a():\n    pass\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "drop a test")
        data = self.run_json()
        kinds = [f for f in data["regression_flags"] if f["kind"] == "tests"]
        self.assertTrue(kinds, data["regression_flags"])
        self.assertEqual(kinds[0]["path"], "tests/test_x.py")

    def test_deleted_test_file_flagged(self):
        make_repo(self.tmp, files={"tests/test_y.py": "def test_a():\n    pass\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/"], tests=["tests/"])], last_synced_commit=sha0)
        os.remove(os.path.join(self.tmp, "tests", "test_y.py"))
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "delete test")
        data = self.run_json()
        kinds = [f for f in data["regression_flags"] if f["kind"] == "tests-deleted"]
        self.assertTrue(kinds, data["regression_flags"])

    def test_p4_03_item1_add_then_trim_within_window_flagged(self):
        make_repo(self.tmp, files={"src/a.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/"], tests=["tests/"])], last_synced_commit=sha0)
        three = "def test_a():\n    pass\n\ndef test_b():\n    pass\n\ndef test_c():\n    pass\n"
        write_files(self.tmp, {"tests/test_fixture.py": three})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "add 3")
        write_files(self.tmp, {"tests/test_fixture.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "trim 1")
        trim_sha = git_sha(self.tmp)
        data = self.run_json()
        kinds = [f for f in data["regression_flags"] if f["kind"] == "tests"]
        self.assertTrue(kinds, data["regression_flags"])
        self.assertEqual(kinds[0]["path"], "tests/test_fixture.py")
        self.assertIn("3 → 2", kinds[0]["detail"])
        self.assertIn(trim_sha[:7], kinds[0]["detail"])

    def test_p4_03_item1_pure_growth_not_flagged(self):
        make_repo(self.tmp, files={"tests/test_x.py": "def test_a():\n    pass\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/"], tests=["tests/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"tests/test_x.py": "def test_a():\n    pass\n\ndef test_b():\n    pass\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "grow")
        data = self.run_json()
        self.assertEqual([f for f in data["regression_flags"] if f["kind"].startswith("tests")], [])


class TestReadListCaps(CatchupTestBase):
    def test_per_system_and_total_caps_non_test_first(self):
        files = {"src/api/init.py": "1\n"}
        for i in range(11):
            files["src/api/f%02d.py" % i] = "1\n"
        make_repo(self.tmp, files=files)
        sha0 = git_sha(self.tmp)
        systems = []
        for sysid in ("api", "core", "mail", "web", "pdf"):
            files_s = {"src/%s/init.py" % sysid: "1\n"}
            for i in range(10):
                files_s["src/%s/f%02d.py" % (sysid, i)] = "1\n"
            write_files(self.tmp, files_s)
            systems.append(make_system(sysid, ["src/%s/" % sysid]))
        for i in range(11):
            write_files(self.tmp, {"src/api/f%02d.py" % i: "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "big change")
        self.write_state(systems, last_synced_commit=sha0)
        data = self.run_json()
        api_reads = [r for r in data["read_list"] if r["system"] == "api"]
        self.assertLessEqual(len(api_reads), 10)
        self.assertLessEqual(len(data["read_list"]), 40)


class TestPendingLifecycle(CatchupTestBase):
    def test_pending_created_last_synced_unchanged(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/api/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"src/api/x.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change")
        sha1 = git_sha(self.tmp)
        r = self.run_catchup()
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["last_synced_commit"], sha0)
        self.assertIsNotNone(st["pending_sync"])
        self.assertEqual(st["pending_sync"]["from"], sha0)
        self.assertEqual(st["pending_sync"]["to"], sha1)

    def test_second_run_keeps_from_extends_to(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/api/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"src/api/x.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change1")
        self.run_catchup()
        write_files(self.tmp, {"src/api/x.py": "3\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change2")
        sha2 = git_sha(self.tmp)
        self.run_catchup()
        st = self.load_state()
        self.assertEqual(st["pending_sync"]["from"], sha0)
        self.assertEqual(st["pending_sync"]["to"], sha2)


class TestDoneAndMarkSynced(CatchupTestBase):
    def _setup_pending(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n", "src/core.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state(
            [make_system("api", ["src/api/"]), make_system("core", ["src/"])],
            last_synced_commit=sha0,
        )
        write_files(self.tmp, {"src/api/x.py": "2\n", "src/core.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change")
        sha1 = git_sha(self.tmp)
        self.run_catchup()
        return sha0, sha1

    def test_done_unknown_id_exits_2(self):
        self._setup_pending()
        r = self.run_catchup("--done", "bogus")
        self.assertEqual(r.returncode, 2)

    def test_mark_synced_refuses_then_force_works(self):
        sha0, sha1 = self._setup_pending()
        r = self.run_catchup("--mark-synced")
        self.assertEqual(r.returncode, 7)
        r = self.run_catchup("--mark-synced", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["last_synced_commit"], sha1)
        self.assertIsNone(st["pending_sync"])

    def test_done_then_mark_synced(self):
        sha0, sha1 = self._setup_pending()
        r = self.run_catchup("--done", "api,core")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_catchup("--mark-synced")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["last_synced_commit"], sha1)


class TestMarkSyncedNullBaseline(CatchupTestBase):
    def test_mark_synced_with_null_baseline_sets_first_run_head(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state(
            [], last_synced_commit=None, pending_sync=None,
            first_run={"status": "in_progress", "head": sha0, "started_at": "2026-01-01T00:00:00Z",
                       "finished_at": None, "passes_done": []},
        )
        r = self.run_catchup("--mark-synced")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["last_synced_commit"], sha0)
        self.assertEqual(st["first_run"]["status"], "done")

    def test_p4_01_item7_mark_synced_appends_close_and_sets_overall(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        sha0 = git_sha(self.tmp)
        systems = [make_system("api", ["src/"]), make_system("web", ["web/"]), make_system("old", ["old/"])]
        systems[0]["health"] = "green"
        systems[1]["health"] = "amber"
        systems[2]["health"] = "red"
        systems[2]["status"] = "retired"
        self.write_state(
            systems, last_synced_commit=None, pending_sync=None,
            first_run={"status": "in_progress", "head": sha0, "started_at": "2026-01-01T00:00:00Z",
                       "finished_at": None, "passes_done": ["kb-init", "digest"]},
        )
        r = self.run_catchup("--mark-synced")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["first_run"]["passes_done"], ["kb-init", "digest", "close"])
        self.assertEqual(st["health"]["overall"], "amber")
        r = self.run_catchup("--mark-synced")
        self.assertEqual(self.load_state()["first_run"]["passes_done"].count("close"), 1)


class TestRewrittenHistory(CatchupTestBase):
    def test_from_not_ancestor_uses_merge_base(self):
        make_repo(self.tmp, files={"a.txt": "0\n"})
        branch = git_raw(self.tmp, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        write_files(self.tmp, {"a.txt": "1\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c1")
        sha1 = git_sha(self.tmp)
        git_raw(self.tmp, "checkout", "-q", "-b", "side", sha1)
        write_files(self.tmp, {"side.txt": "1\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "side-commit")
        side_sha = git_sha(self.tmp)
        git_raw(self.tmp, "checkout", "-q", branch)
        write_files(self.tmp, {"a.txt": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c2")
        self.write_state([], last_synced_commit=side_sha)
        data = self.run_json()
        self.assertEqual(data["from"], sha1)

    def test_from_missing_exits_5(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        self.write_state([], last_synced_commit="0" * 40)
        r = self.run_catchup()
        self.assertEqual(r.returncode, 5)


class TestNonGitAndNullBaseline(CatchupTestBase):
    def test_non_git_exits_3(self):
        write_files(self.tmp, {"a.txt": "1\n"})
        self.write_state([], last_synced_commit="0" * 40)
        r = self.run_catchup()
        self.assertEqual(r.returncode, 3)

    def test_null_baseline_exits_4(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        self.write_state([], last_synced_commit=None, pending_sync=None)
        r = self.run_catchup()
        self.assertEqual(r.returncode, 4)

    def test_p4_01_item4_null_baseline_still_prints_budget(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        self.write_state([], last_synced_commit=None, pending_sync=None)
        limits_path = os.path.join(self.tmp, "limits.json")
        with open(limits_path, "w") as f:
            json.dump({"rate_limits": {"five_hour": {"used_percentage": 12.0, "resets_at": None},
                                       "seven_day": {"used_percentage": 40.0, "resets_at": None}},
                       "_written_at": 1700000000}, f)
        r = self.run_catchup("--limits-file", limits_path)
        self.assertEqual(r.returncode, 4)
        self.assertIn("Budget: five_hour 12.0%", r.stdout)


class TestJsonKeys(CatchupTestBase):
    def test_json_keys_present(self):
        make_repo(self.tmp, files={"src/api/x.py": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([make_system("api", ["src/api/"])], last_synced_commit=sha0)
        write_files(self.tmp, {"src/api/x.py": "2\n"})
        git_raw(self.tmp, "add", "-A")
        git_raw(self.tmp, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "change")
        data = self.run_json()
        for key in (
            "from", "to", "commits", "commits_total", "status", "budget", "systems",
            "orchestration", "skills", "unmapped", "new_system_candidates",
            "regression_flags", "read_list", "subjects",
        ):
            self.assertIn(key, data, key)


class TestBudgetLine(CatchupTestBase):
    def test_budget_line_with_fixture_and_without(self):
        make_repo(self.tmp, files={"a.txt": "1\n"})
        sha0 = git_sha(self.tmp)
        self.write_state([], last_synced_commit=sha0)
        limits_path = os.path.join(self.tmp, "limits.json")
        with open(limits_path, "w") as f:
            json.dump({
                "rate_limits": {
                    "five_hour": {"used_percentage": 16.0, "resets_at": 9999999999},
                    "seven_day": {"used_percentage": 56.0, "resets_at": 9999999999},
                },
                "_written_at": 1700000000,
            }, f)
        r = self.run_catchup("--limits-file", limits_path)
        self.assertIn("Budget: five_hour 16.0%", r.stdout)

        r2 = self.run_catchup("--limits-file", os.path.join(self.tmp, "does-not-exist.json"))
        self.assertIn("Budget: unknown", r2.stdout)


if __name__ == "__main__":
    unittest.main()
