import json
import os
import shutil
import sys
import tempfile
import unittest
from shutil import which

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "skill", "scripts"))
sys.path.insert(0, _HERE)
from _fixtures import make_repo, run_script, write_files

HAS_GIT = which("git") is not None


class DigestTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, files):
        write_files(self.tmp, files)

    def run_digest(self, *args):
        return run_script("project_digest.py", *(["--project", self.tmp] + list(args)), cwd=self.tmp)

    def run_json(self, *args):
        r = self.run_digest("--json", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def ids(self, data):
        return {s["id"] for s in data["systems"]}


class TestPythonPackage(DigestTestBase):
    def test_one_system_per_subpackage_plus_core(self):
        self.write({
            "pkg/__init__.py": "",
            "pkg/sub1/__init__.py": "",
            "pkg/sub1/mod.py": "x = 1\n",
            "pkg/sub2/__init__.py": "",
            "pkg/sub2/mod.py": "y = 2\n",
            "root.py": "z = 3\n",
        })
        data = self.run_json()
        self.assertIn("sub1", self.ids(data))
        self.assertIn("sub2", self.ids(data))
        self.assertIn("core", self.ids(data))


class TestCollectionDirs(DigestTestBase):
    def test_per_child_systems(self):
        self.write({
            "bin/x/main.py": "print('x')\n",
            "bin/y/main.py": "print('y')\n",
            "skills/a/SKILL.md": "# a\n",
        })
        data = self.run_json()
        ids = self.ids(data)
        self.assertIn("x", ids)
        self.assertIn("y", ids)
        self.assertIn("a", ids)


class TestVerticalSlices(DigestTestBase):
    def test_slice_detected_and_stoplisted_ignored(self):
        self.write({
            "cli/orders.py": "def run():\n    pass\n",
            "pipeline/orders.py": "def run():\n    pass\n",
            "report/orders.py": "def run():\n    pass\n",
            "cli/utils.py": "def helper():\n    pass\n",
            "pipeline/utils.py": "def helper():\n    pass\n",
        })
        data = self.run_json()
        stems = {s["stem"] for s in data["slices"]}
        self.assertIn("orders", stems)
        self.assertNotIn("utils", stems)
        orders = next(s for s in data["slices"] if s["stem"] == "orders")
        self.assertIn("cli", orders["dirs"])
        self.assertIn("pipeline", orders["dirs"])
        self.assertIn("report", orders["dirs"])

    def test_p4_02_item2_slice_paths_are_stem_files(self):
        self.write({
            "pkg/__init__.py": "",
            "pkg/cli/__init__.py": "", "pkg/cli/invoices.py": "x = 1\n", "pkg/cli/other.py": "x = 1\n",
            "pkg/pipeline/__init__.py": "", "pkg/pipeline/invoices.py": "x = 1\n",
        })
        data = self.run_json()
        invoices = next(s for s in data["systems"] if s["id"] == "invoices")
        self.assertEqual(invoices["paths"], ["pkg/cli/invoices.py", "pkg/pipeline/invoices.py"])
        self.assertEqual(invoices["code_files"], 2)

    def test_p4_02_item4_mirrored_yaml_stems_are_not_slices(self):
        self.write({
            "config/filters.yaml": "a: 1\n",
            "data/filters.yaml": "a: 1\n",
            "cli/orders.py": "x = 1\n",
            "report/orders.yaml": "a: 1\n",
        })
        data = self.run_json()
        stems = {s["stem"] for s in data["slices"]}
        self.assertNotIn("filters", stems)
        self.assertNotIn("orders", stems)


class TestP402TestMirror(DigestTestBase):
    def test_p4_02_item3_flat_tests_unit_fills_tests(self):
        self.write({
            "pkg/__init__.py": "",
            "pkg/cli/__init__.py": "", "pkg/cli/invoices.py": "x = 1\n",
            "pkg/pipeline/__init__.py": "", "pkg/pipeline/invoices.py": "x = 1\n",
            "pkg/mail/__init__.py": "", "pkg/mail/fetch.py": "x = 1\n",
            "tests/unit/test_invoices.py": "def test_a():\n    pass\n",
            "tests/unit/test_invoices_detect.py": "def test_b():\n    pass\n",
            "tests/mail/test_fetch.py": "def test_c():\n    pass\n",
        })
        data = self.run_json()
        by_id = {s["id"]: s for s in data["systems"]}
        self.assertEqual(by_id["invoices"]["tests"], ["tests/unit/test_invoices*"])
        self.assertEqual(by_id["invoices"]["test_fns"], 2)
        self.assertEqual(by_id["mail"]["tests"], ["tests/mail/"])


class TestP401ShebangLanguage(DigestTestBase):
    def test_p4_01_item14_extensionless_shebang_counted(self):
        self.write({
            "bin/orch": "#!/usr/bin/env bash\necho hi\n",
            "bin/tool": "#!/usr/bin/env python3\nprint(1)\n",
            "LICENSE": "MIT\n",
        })
        data = self.run_json()
        langs = data["shape"]["languages"]
        self.assertEqual(langs["Shell"]["files"], 1)
        self.assertEqual(langs["Python"]["files"], 1)


class TestOrchestrationExcluded(DigestTestBase):
    def test_excluded_from_systems_but_counted_worker_names_only(self):
        sentinel = "SENTINEL_SECRET_TOKEN_DO_NOT_LEAK"
        self.write({
            "src/app.py": "import os\n",
            "orchestration/plan.md": "# plan\n## Objective\nDo the thing.\n",
            "orchestration/workers/p1-01-foo/result.md": "STATUS: DONE\n%s\n" % sentinel,
        })
        r = self.run_digest()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(sentinel, r.stdout)
        self.assertNotIn("p1-01-foo", r.stdout)
        data = self.run_json()
        self.assertNotIn("p1-01-foo", self.ids(data))
        self.assertTrue(data["orchestration"]["present"])
        self.assertEqual(data["orchestration"]["dirs"]["workers"]["count"], 1)
        self.assertGreater(data["shape"]["bytes_by_category"]["orchestration"], 0)


class TestTestsCounted(DigestTestBase):
    def test_functions_and_parametrize_counted(self):
        self.write({
            "tests/test_things.py": (
                "import pytest\n\n"
                "@pytest.mark.parametrize('x', [1, 2])\n"
                "def test_one(x):\n    assert x\n\n"
                "def test_two():\n    assert True\n"
            ),
        })
        data = self.run_json()
        self.assertEqual(data["tests"]["functions"], 2)
        self.assertEqual(data["tests"]["parametrize"], 1)


class TestMaxLines(DigestTestBase):
    def test_big_tree_respects_max_lines(self):
        files = {}
        for i in range(60):
            for j in range(3):
                files["big/sub%03d/f%d.py" % (i, j)] = "x = %d\n" % j
        self.write(files)
        r = self.run_digest("--max-lines", "60")
        self.assertEqual(r.returncode, 0, r.stderr)
        n = len(r.stdout.splitlines())
        self.assertLessEqual(n, 75)
        r2 = self.run_digest("--max-lines", "5000")
        n2 = len(r2.stdout.splitlines())
        self.assertGreater(n2, n)


class TestJsonShape(DigestTestBase):
    def test_json_parses_and_has_keys(self):
        self.write({"a.py": "x = 1\n"})
        data = self.run_json()
        for key in (
            "project", "head", "commits", "first_date", "last_date", "shape",
            "entry_points", "tests", "docs", "orchestration", "skills",
            "systems", "slices", "hubs", "edges", "signals", "recent",
        ):
            self.assertIn(key, data, key)


class TestNonGit(DigestTestBase):
    def test_non_git_dir_works(self):
        self.write({"a.py": "x = 1\n"})
        r = self.run_digest()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not a git repo", r.stdout)


class TestJsRelativeImport(DigestTestBase):
    def test_relative_import_edge(self):
        self.write({
            "apps/foo/index.js": "const h = require('../bar/helper');\n",
            "apps/bar/helper.js": "module.exports = {};\n",
        })
        data = self.run_json()
        self.assertTrue(
            any(e["from"] == "foo" and e["to"] == "bar" for e in data["edges"]),
            data["edges"],
        )


class TestLargeFileSkipped(DigestTestBase):
    def test_files_over_1mb_skipped(self):
        self.write({"a.py": "x = 1\n"})
        big_path = os.path.join(self.tmp, "big.bin")
        with open(big_path, "wb") as f:
            f.write(b"0" * (1024 * 1024 + 10))
        data = self.run_json()
        self.assertEqual(data["shape"]["large"], 1)
        self.assertEqual(data["shape"]["files"], 1)


if __name__ == "__main__":
    unittest.main()
