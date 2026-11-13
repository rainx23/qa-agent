"""P3 SQL-only Manifest contract tests; all writes stay in TemporaryDirectory."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

P1_TOOLS = Path(__file__).resolve().parents[2] / "testcase-design" / "tools"
sys.path.insert(0, str(P1_TOOLS))
import manifest  # noqa: E402


class SqlOnlyManifestContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="p3-sql-manifest-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "996003-P3-SQL"
        self.source = self.base / "sources"
        self.source.mkdir()
        self.spec = self.base / "publish-spec.json"
        self.version_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")

    def write_query(self, name, sql):
        source = self.source / name
        source.write_text(sql, encoding="utf-8")
        return source

    def invoke(self, command, *args):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = manifest.main([command, *map(str, args)])
        return code, json.loads(buffer.getvalue())

    def publish(self, files, base_version=None, case_changes_missing=True):
        payload = {
            "requirement": {"id": "996003", "name": "P3-SQL"},
            "expected_base_version": base_version,
            "delivery_status": "complete",
            "artifacts": [
                {"category": "sql", "role": role,
                 "source_path": str(path), "path": f"sql/{path.name}"}
                for role, path in files
            ],
            "lineage": {},
            "retire_artifacts": [],
        }
        if not case_changes_missing:
            payload["case_changes"] = {"added": [], "updated": [], "retired": []}
        self.spec.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return self.invoke("publish", self.root, self.spec)

    def latest(self):
        code, result = self.invoke("inspect", self.root)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"], "MANIFEST_BASELINE_READY")
        return result["latest_version"]

    def current_manifest(self):
        return json.loads((self.root / "versions" / self.latest() / "manifest.json").read_text(encoding="utf-8"))

    def test_first_sql_only_publish_and_validate(self):
        find = self.write_query("find-samples.sql", "select 1;\n")
        verify = self.write_query("verify-result.sql", "select 2;\n")
        code, result = self.publish([("find-samples", find), ("verify-result", verify)])
        self.assertEqual(code, 0, result)
        self.assertEqual(result["result"], "MANIFEST_PUBLISH_PASS")
        self.assertEqual(result["version_id"], f"{self.version_date}-v1")
        data = self.current_manifest()
        self.assertEqual(data["schema_version"], "1")
        self.assertEqual(data["case_snapshot"], [])
        self.assertEqual({a["role"] for a in data["artifacts"]},
                         {"find-samples", "verify-result"})
        self.assertEqual(self.invoke("validate", self.root)[1]["result"],
                         "MANIFEST_HISTORY_PASS")

    def test_scenario_coverage_markdown_can_be_published_with_sql(self):
        scenario = self.write_query("scenario-coverage.md", "# 场景清单\n")
        query = self.write_query("sql-design.sql", "-- SQL-01\nselect 1;\n")
        code, result = self.publish([
            ("scenario-coverage", scenario),
            ("sql-design", query),
        ])
        self.assertEqual(code, 0, result)
        latest = self.latest()
        data = self.current_manifest()
        by_role = {item["role"]: item for item in data["artifacts"]}
        self.assertEqual(by_role["scenario-coverage"]["category"], "sql")
        self.assertEqual(
            by_role["scenario-coverage"]["path"],
            f"sql/{latest}/scenario-coverage.md",
        )
        self.assertTrue((self.root / "sql" / latest / "scenario-coverage.md").is_file())
        code, validation = self.invoke("validate", self.root)
        self.assertEqual(code, 0, validation)
        self.assertEqual(validation["result"], "MANIFEST_HISTORY_PASS")

    def test_changed_role_does_not_copy_unchanged_role(self):
        find = self.write_query("find-samples.sql", "select 1;\n")
        verify = self.write_query("verify-result.sql", "select 2;\n")
        self.assertEqual(self.publish([("find-samples", find), ("verify-result", verify)])[0], 0)
        first = self.latest()
        old_find = (self.root / "sql" / first / "find-samples.sql").read_bytes()
        old_verify = (self.root / "sql" / first / "verify-result.sql").read_bytes()
        find.write_text("select 3;\n", encoding="utf-8")
        self.assertEqual(self.publish([("find-samples", find)], first)[0], 0)
        data = self.current_manifest()
        by_role = {a["role"]: a for a in data["artifacts"]}
        self.assertEqual(by_role["find-samples"]["source_version"], data["version_id"])
        self.assertEqual(by_role["verify-result"]["source_version"], first)
        self.assertEqual(by_role["verify-result"]["change"], "unchanged")
        self.assertEqual((self.root / "sql" / first / "find-samples.sql").read_bytes(), old_find)
        self.assertEqual((self.root / "sql" / first / "verify-result.sql").read_bytes(), old_verify)
        self.assertFalse((self.root / "sql" / data["version_id"] / "verify-result.sql").exists())
        self.assertEqual(self.invoke("validate", self.root)[0], 0)

    def test_add_new_role_keeps_existing_roles(self):
        find = self.write_query("find-samples.sql", "select 1;\n")
        verify = self.write_query("verify-result.sql", "select 2;\n")
        self.assertEqual(self.publish([("find-samples", find)])[0], 0)
        first = self.latest()
        self.assertEqual(self.publish([("verify-result", verify)], first)[0], 0)
        data = self.current_manifest()
        self.assertEqual(len(data["artifacts"]), 2)
        self.assertEqual({x["role"] for x in data["artifacts"]},
                         {"find-samples", "verify-result"})

    def test_no_change_does_not_publish_new_version(self):
        find = self.write_query("sql-design.sql", "select 1;\n")
        self.assertEqual(self.publish([("sql-design", find)])[0], 0)
        current = self.latest()
        code, result = self.publish([("sql-design", find)], current)
        self.assertEqual(code, 1)
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(self.latest(), current)

    def test_stale_baseline_rejected_without_new_version(self):
        find = self.write_query("sql-design.sql", "select 1;\n")
        self.assertEqual(self.publish([("sql-design", find)])[0], 0)
        first = self.latest()
        find.write_text("select 2;\n", encoding="utf-8")
        self.assertEqual(self.publish([("sql-design", find)], first)[0], 0)
        second = self.latest()
        find.write_text("select 3;\n", encoding="utf-8")
        code, result = self.publish([("sql-design", find)], first)
        self.assertEqual(code, 1)
        self.assertEqual(result["result"], "FAIL")
        self.assertEqual(self.latest(), second)

    def test_historical_tamper_detected_and_new_publish_blocked(self):
        find = self.write_query("sql-design.sql", "select 1;\n")
        self.assertEqual(self.publish([("sql-design", find)])[0], 0)
        first = self.latest()
        (self.root / "sql" / first / "sql-design.sql").write_text("select 999;\n", encoding="utf-8")
        code, result = self.invoke("validate", self.root)
        self.assertEqual(code, 1)
        self.assertIn("SHA-256", result["error"])
        find.write_text("select 2;\n", encoding="utf-8")
        code, _ = self.publish([("sql-design", find)], first)
        self.assertEqual(code, 1)
        inspect_code, inspect_result = self.invoke("inspect", self.root)
        self.assertEqual(inspect_code, 1)
        self.assertIn("SHA-256", inspect_result["error"])
        self.assertFalse((self.root / "versions" / f"{self.version_date}-v2").exists())

    def test_empty_p1_case_changes_field_is_not_a_sql_only_contract(self):
        find = self.write_query("sql-design.sql", "select 1;\n")
        code, result = self.publish([("sql-design", find)], case_changes_missing=False)
        self.assertEqual(code, 1)
        self.assertEqual(result["result"], "FAIL")
        self.assertFalse(self.root.exists() and any(self.root.glob("*-v*")))

    def test_path_traversal_rejected(self):
        source = self.write_query("sql-design.sql", "select 1;\n")
        payload = {
            "requirement": {"id": "996003", "name": "P3-SQL"},
            "expected_base_version": None,
            "delivery_status": "complete",
            "artifacts": [{"category": "sql", "role": "sql-design",
                           "source_path": str(source), "path": "sql/../unsafe.sql"}]
        }
        self.spec.write_text(json.dumps(payload), encoding="utf-8")
        code, result = self.invoke("publish", self.root, self.spec)
        self.assertEqual(code, 1)
        self.assertEqual(result["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
