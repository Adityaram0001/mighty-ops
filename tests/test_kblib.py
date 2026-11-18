import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skill", "scripts"))
import kblib


class TestFindKb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pointer_line_beats_default(self):
        os.makedirs(os.path.join(self.tmp, "custom-kb"))
        with open(os.path.join(self.tmp, "custom-kb", "state.json"), "w") as f:
            json.dump({"schema": "mighty-ops-kb/1"}, f)
        os.makedirs(os.path.join(self.tmp, "mighty-ops"))
        with open(os.path.join(self.tmp, "mighty-ops", "state.json"), "w") as f:
            json.dump({"schema": "mighty-ops-kb/1"}, f)
        with open(os.path.join(self.tmp, "CLAUDE.md"), "w") as f:
            f.write("- Systems knowledge base: `custom-kb/` (owned by ...).\n")
        found = kblib.find_kb(self.tmp)
        self.assertEqual(found, os.path.join(self.tmp, "custom-kb"))

    def test_default_dir(self):
        os.makedirs(os.path.join(self.tmp, "mighty-ops"))
        with open(os.path.join(self.tmp, "mighty-ops", "state.json"), "w") as f:
            json.dump({"schema": "mighty-ops-kb/1"}, f)
        found = kblib.find_kb(self.tmp)
        self.assertEqual(found, os.path.join(self.tmp, "mighty-ops"))

    def test_schema_scan(self):
        os.makedirs(os.path.join(self.tmp, "weird-name"))
        with open(os.path.join(self.tmp, "weird-name", "state.json"), "w") as f:
            json.dump({"schema": "mighty-ops-kb/1"}, f)
        found = kblib.find_kb(self.tmp)
        self.assertEqual(found, os.path.join(self.tmp, "weird-name"))

    def test_schema_scan_ignores_wrong_schema(self):
        os.makedirs(os.path.join(self.tmp, "other-dir"))
        with open(os.path.join(self.tmp, "other-dir", "state.json"), "w") as f:
            json.dump({"schema": "something-else/1"}, f)
        found = kblib.find_kb(self.tmp)
        self.assertIsNone(found)

    def test_none_found(self):
        self.assertIsNone(kblib.find_kb(self.tmp))


class TestSystemForPath(unittest.TestCase):
    def setUp(self):
        self.systems = [
            {"id": "api", "paths": ["src/app/api/", "config/api.yaml"]},
            {"id": "api-admin", "paths": ["src/app/api/admin/"]},
            {"id": "docs", "paths": ["docs/*.md"]},
        ]

    def test_longest_prefix_wins(self):
        self.assertEqual(
            kblib.system_for_path("src/app/api/admin/handler.py", self.systems, "mighty-ops", []),
            "api-admin",
        )
        self.assertEqual(
            kblib.system_for_path("src/app/api/other.py", self.systems, "mighty-ops", []),
            "api",
        )

    def test_single_file_prefix(self):
        self.assertEqual(
            kblib.system_for_path("config/api.yaml", self.systems, "mighty-ops", []),
            "api",
        )

    def test_fnmatch_pattern(self):
        self.assertEqual(
            kblib.system_for_path("docs/readme.md", self.systems, "mighty-ops", []),
            "docs",
        )
        self.assertEqual(
            kblib.system_for_path("other/readme.md", self.systems, "mighty-ops", []),
            "(unmapped)",
        )

    def test_kb_dir(self):
        self.assertEqual(
            kblib.system_for_path("mighty-ops/state.json", self.systems, "mighty-ops", []),
            "(kb)",
        )

    def test_noise(self):
        self.assertEqual(
            kblib.system_for_path("orchestration/plan.md", self.systems, "mighty-ops", ["orchestration/"]),
            "(noise:orchestration/)",
        )

    def test_skills(self):
        self.assertEqual(
            kblib.system_for_path(".claude/skills/foo/SKILL.md", self.systems, "mighty-ops", ["orchestration/"]),
            "(skills)",
        )

    def test_unmapped(self):
        self.assertEqual(
            kblib.system_for_path("random/thing.py", self.systems, "mighty-ops", ["orchestration/"]),
            "(unmapped)",
        )


class TestCountTestFns(unittest.TestCase):
    def test_python(self):
        text = "def test_a():\n    pass\nasync def test_b():\n    pass\ndef not_a_test():\n    pass\n"
        self.assertEqual(kblib.count_test_fns(text), 2)

    def test_js(self):
        text = "it('does a thing', () => {})\ntest('another', () => {})\nfunction other() {}\n"
        self.assertEqual(kblib.count_test_fns(text), 2)

    def test_mixed_and_indented(self):
        text = "class Foo:\n    def test_method(self):\n        pass\n"
        self.assertEqual(kblib.count_test_fns(text), 1)

    def test_none(self):
        self.assertEqual(kblib.count_test_fns("def helper():\n    pass\n"), 0)


class TestIsTestPath(unittest.TestCase):
    def test_tests_dir(self):
        self.assertTrue(kblib.is_test_path("pkg/tests/test_foo.py"))

    def test_test_prefix(self):
        self.assertTrue(kblib.is_test_path("pkg/test_foo.py"))

    def test_test_suffix(self):
        self.assertTrue(kblib.is_test_path("pkg/foo_test.py"))

    def test_js_spec(self):
        self.assertTrue(kblib.is_test_path("src/foo.spec.ts"))
        self.assertTrue(kblib.is_test_path("src/foo.test.js"))

    def test_not_a_test(self):
        self.assertFalse(kblib.is_test_path("pkg/foo.py"))


class TestReadLimits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_fixture_fresh(self):
        path = os.path.join(self.tmp, "limits.json")
        data = {
            "rate_limits": {
                "five_hour": {"used_percentage": 16.0, "resets_at": 1234567890},
                "seven_day": {"used_percentage": 56.0, "resets_at": 1234599999},
            },
            "_written_at": time.time(),
            "_source": "orch",
        }
        with open(path, "w") as f:
            json.dump(data, f)
        result = kblib.read_limits(path)
        self.assertTrue(result["available"])
        self.assertEqual(result["five_hour"]["used"], 16.0)
        self.assertFalse(result["stale"])

    def test_stale_flag(self):
        path = os.path.join(self.tmp, "limits.json")
        data = {
            "rate_limits": {
                "five_hour": {"used_percentage": 1.0, "resets_at": 1},
                "seven_day": {"used_percentage": 1.0, "resets_at": 1},
            },
            "_written_at": time.time() - 3600,
        }
        with open(path, "w") as f:
            json.dump(data, f)
        result = kblib.read_limits(path)
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])

    def test_missing_file(self):
        result = kblib.read_limits(os.path.join(self.tmp, "nope.json"))
        self.assertFalse(result["available"])

    def test_malformed_json(self):
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w") as f:
            f.write("{not json")
        result = kblib.read_limits(path)
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
