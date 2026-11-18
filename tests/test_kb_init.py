import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from shutil import which

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "skill", "scripts"))
sys.path.insert(0, _HERE)
import kblib
from _fixtures import make_repo, run_script

HAS_GIT = which("git") is not None


class KbInitTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_init(self, *args):
        return run_script("kb_init.py", *(["--project", self.tmp] + list(args)), cwd=self.tmp)

    def load_state(self, kb_dir="mighty-ops"):
        with open(os.path.join(self.tmp, kb_dir, "state.json")) as f:
            return json.load(f)


class TestCreateTree(KbInitTestBase):
    def test_creates_full_tree_in_empty_dir(self):
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        kb = os.path.join(self.tmp, "mighty-ops")
        self.assertTrue(os.path.isfile(os.path.join(kb, "state.json")))
        self.assertTrue(os.path.isfile(os.path.join(kb, "README.md")))
        self.assertTrue(os.path.isfile(os.path.join(kb, "harmony.md")))
        self.assertTrue(os.path.isfile(os.path.join(kb, "glossary.md")))
        self.assertTrue(os.path.isfile(os.path.join(kb, "roadmap", "roadmap.md")))
        self.assertTrue(os.path.isfile(os.path.join(kb, "roadmap", "ideas.md")))
        for d in ("decisions", "inbox", "outbox", "exchanges", "digests"):
            self.assertTrue(os.path.isdir(os.path.join(kb, d)))
        for fname in kblib.REQUIRED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(kb, "systems", "api", fname)))

    def test_idempotent_second_run(self):
        self.run_init("--systems", "api")
        kb = os.path.join(self.tmp, "mighty-ops")
        before = {}
        for root, _, files in os.walk(kb):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    before[p] = (os.path.getmtime(p), fh.read())
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        after = {}
        for root, _, files in os.walk(kb):
            for f in files:
                p = os.path.join(root, f)
                with open(p, "rb") as fh:
                    after[p] = (os.path.getmtime(p), fh.read())
        self.assertEqual(set(before), set(after))
        for p in before:
            self.assertEqual(before[p][1], after[p][1], "content changed: %s" % p)

    def test_p3_gap_rerun_across_second_boundary_keeps_state_bytes(self):
        self.run_init("--systems", "api")
        path = os.path.join(self.tmp, "mighty-ops", "state.json")
        with open(path, "rb") as fh:
            before = fh.read()
        time.sleep(1.1)
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(path, "rb") as fh:
            self.assertEqual(before, fh.read())

    def test_existing_hand_edited_file_kept(self):
        self.run_init("--systems", "api")
        path = os.path.join(self.tmp, "mighty-ops", "systems", "api", "findings.md")
        with open(path, "w") as f:
            f.write("hand edited content\n")
        self.run_init("--systems", "api")
        with open(path) as f:
            self.assertEqual(f.read(), "hand edited content\n")

    def test_systems_json_from_digest_shape(self):
        digest = {"systems": [{"id": "api", "name": "HTTP API", "kind": "feature", "paths": ["src/"]}]}
        path = os.path.join(self.tmp, "digest.json")
        with open(path, "w") as f:
            json.dump(digest, f)
        r = self.run_init("--systems-json", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        ids = [s["id"] for s in st["systems"]]
        self.assertIn("api", ids)

    def test_systems_json_bare_list(self):
        path = os.path.join(self.tmp, "bare.json")
        with open(path, "w") as f:
            json.dump([{"id": "storage"}], f)
        r = self.run_init("--systems-json", path)
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        ids = [s["id"] for s in st["systems"]]
        self.assertIn("storage", ids)

    def test_bad_id_exits_2(self):
        r = self.run_init("--systems", "Bad_ID!")
        self.assertEqual(r.returncode, 2)
        self.assertIn("error:", r.stderr)

    def test_claude_md_append_once_not_duplicated(self):
        with open(os.path.join(self.tmp, "CLAUDE.md"), "w") as f:
            f.write("# project notes\n")
        self.run_init("--systems", "api", "--claude-md", "append")
        with open(os.path.join(self.tmp, "CLAUDE.md")) as f:
            text1 = f.read()
        self.assertIn("Systems knowledge base:", text1)
        self.run_init("--systems", "api", "--claude-md", "append")
        with open(os.path.join(self.tmp, "CLAUDE.md")) as f:
            text2 = f.read()
        self.assertEqual(text1.count("Systems knowledge base:"), 1)
        self.assertEqual(text2.count("Systems knowledge base:"), 1)

    def test_claude_md_skip(self):
        self.run_init("--systems", "api", "--claude-md", "skip")
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, "CLAUDE.md")))

    def test_claude_md_create(self):
        self.run_init("--systems", "api", "--claude-md", "create")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "CLAUDE.md")))
        with open(os.path.join(self.tmp, "CLAUDE.md")) as f:
            self.assertIn("Systems knowledge base:", f.read())

    def test_claude_md_append_without_existing_file_noop(self):
        self.run_init("--systems", "api", "--claude-md", "append")
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, "CLAUDE.md")))

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_non_git_dir_commit_policy_never_head_null(self):
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["commit_policy"], "never")
        self.assertIsNone(st["first_run"]["head"])

    @unittest.skipUnless(HAS_GIT, "git not installed")
    def test_git_dir_head_recorded(self):
        make_repo(self.tmp, files={"a.txt": "x\n"})
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        self.assertEqual(st["commit_policy"], "auto")
        self.assertIsNotNone(st["first_run"]["head"])
        self.assertRegex(st["first_run"]["head"], r"^[0-9a-f]{40}$")

    def test_dry_run_writes_nothing(self):
        r = self.run_init("--systems", "api", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, "mighty-ops")))

    def test_kb_dir_mismatch_exits_6(self):
        self.run_init("--systems", "api")
        r = self.run_init("--systems", "api", "--kb-dir", "other-name")
        self.assertEqual(r.returncode, 6)

    def test_existing_non_kb_dir_exits_6(self):
        os.makedirs(os.path.join(self.tmp, "mighty-ops"))
        with open(os.path.join(self.tmp, "mighty-ops", "somefile.txt"), "w") as f:
            f.write("not a kb\n")
        r = self.run_init("--systems", "api")
        self.assertEqual(r.returncode, 6)


class TestAddSystem(KbInitTestBase):
    def test_add_system_adds_folder_and_state_entry(self):
        self.run_init("--systems", "api")
        r = self.run_init("--add-system", "storage", "--paths", "src/storage/")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        ids = [s["id"] for s in st["systems"]]
        self.assertIn("storage", ids)
        for fname in kblib.REQUIRED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "mighty-ops", "systems", "storage", fname)))

    def test_add_paths(self):
        self.run_init("--systems", "api")
        r = run_script(
            "kb_init.py",
            "--project",
            self.tmp,
            "--add-paths",
            "api",
            "src/newpath/",
            cwd=self.tmp,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        api = next(s for s in st["systems"] if s["id"] == "api")
        self.assertIn("src/newpath/", api["paths"])

    def test_add_paths_unknown_id_exits_2(self):
        self.run_init("--systems", "api")
        r = run_script(
            "kb_init.py", "--project", self.tmp, "--add-paths", "nope", "x/", cwd=self.tmp
        )
        self.assertEqual(r.returncode, 2)


class TestSplitMerge(KbInitTestBase):
    def test_split_marks_old_and_superseded_lines_and_derived_from(self):
        self.run_init("--systems", "old")
        r = self.run_init(
            "--split", "old", "--into", "a,b", "--paths-a", "src/a/", "--paths-b", "src/b/"
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        by_id = {s["id"]: s for s in st["systems"]}
        self.assertEqual(by_id["old"]["status"], "split")
        self.assertEqual(sorted(by_id["old"]["superseded_by"]), ["a", "b"])
        self.assertEqual(by_id["a"]["derived_from"], ["old"])
        self.assertEqual(by_id["b"]["derived_from"], ["old"])
        with open(os.path.join(self.tmp, "mighty-ops", "systems", "old", "findings.md")) as f:
            text = f.read()
        self.assertIn("Superseded: split into a, b on", text)
        for fname in kblib.REQUIRED_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "mighty-ops", "systems", "a", fname)))
            self.assertTrue(os.path.isfile(os.path.join(self.tmp, "mighty-ops", "systems", "b", fname)))

    def test_split_unknown_old_exits_2(self):
        self.run_init("--systems", "api")
        r = self.run_init(
            "--split", "nope", "--into", "a,b", "--paths-a", "x/", "--paths-b", "y/"
        )
        self.assertEqual(r.returncode, 2)

    def test_merge_symmetric(self):
        self.run_init("--systems", "a,b")
        r = self.run_init("--merge", "a,b", "--into", "c")
        self.assertEqual(r.returncode, 0, r.stderr)
        st = self.load_state()
        by_id = {s["id"]: s for s in st["systems"]}
        self.assertEqual(by_id["a"]["status"], "merged")
        self.assertEqual(by_id["b"]["status"], "merged")
        self.assertEqual(by_id["a"]["superseded_by"], ["c"])
        self.assertEqual(by_id["b"]["superseded_by"], ["c"])
        self.assertEqual(sorted(by_id["c"]["derived_from"]), ["a", "b"])
        with open(os.path.join(self.tmp, "mighty-ops", "systems", "a", "findings.md")) as f:
            self.assertIn("Superseded: merged into c on", f.read())

    def test_merge_unknown_id_exits_2(self):
        self.run_init("--systems", "a")
        r = self.run_init("--merge", "a,nope", "--into", "c")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
