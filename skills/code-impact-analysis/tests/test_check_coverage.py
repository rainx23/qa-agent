"""Tests of the fixed coverage-table contract, not business or Markdown validity."""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check_coverage.py"
spec = importlib.util.spec_from_file_location("check_coverage", TOOL)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def candidates(*ids):
    return [{"id": key, "source": "synthetic current source/config"} for key in ids]


def report(rows, state="COMPLETE"):
    return "\n".join([
        "### 结论摘要", "Other report content is reviewed by AI.", "",
        "### 覆盖对账", "", f"覆盖完整性：{state}", "",
        "| 对象标识 | 静态核查 | 解析目标 | CHK/EV或理由 |",
        "|---|---|---|---|",
        *[f"| {key} | {status} | {mapping} | {detail} |" for key, status, mapping, detail in rows],
        "", "### 业务核对矩阵", "Normal business report.", "",
        "### EV 证据索引", "Evidence is reviewed by AI.",
    ])


def row(key, state="PASS", mapping="-", detail="CHK-001 EV-001"):
    return key, state, mapping, detail


class CoverageTest(unittest.TestCase):
    def check(self, ids, rows, state="COMPLETE"):
        return mod.reconcile(candidates(*ids), report(rows, state))

    def test_complete_with_confirmed_defect_and_shared_check(self):
        r = self.check(["module-a/page", "module-b/api"],
                       [row("module-a/page"), row("module-b/api", "FAIL")])
        self.assertEqual(r["result"], "COMPLETE")

    def test_missing_old_new_and_variant_objects(self):
        ids = ["old/card", "new/export", "api:mode-a", "api:mode-b"]
        r = self.check(ids, [row("api:mode-a")])
        self.assertEqual(r["missing"], ["api:mode-b", "new/export", "old/card"])
        self.assertEqual(r["result"], "INVALID")

    def test_extra_report_object(self):
        r = self.check(["a"], [row("a"), row("new")])
        self.assertEqual(r["extra"], ["new"])
        self.assertEqual(r["result"], "INVALID")

    def test_duplicate_candidate_and_report(self):
        self.assertIn("duplicate candidate: a", self.check(["a", "a"], [row("a")])["errors"])
        self.assertIn("duplicate report object: a", self.check(["a"], [row("a"), row("a")])["errors"])

    def test_unknown_partial_and_false_complete(self):
        rows = [row("a", "UNKNOWN", detail="unresolved dynamic path")]
        self.assertEqual(self.check(["a"], rows, "PARTIAL")["result"], "PARTIAL")
        self.assertEqual(self.check(["a"], rows)["result"], "INVALID")

    def test_partial_cannot_hide_missing_or_lack_unknown(self):
        self.assertEqual(self.check(["a", "b"], [row("a", "UNKNOWN")], "PARTIAL")["result"], "INVALID")
        self.assertEqual(self.check(["a"], [row("a")], "PARTIAL")["result"], "INVALID")

    def test_empty_discovery_cannot_claim_complete(self):
        self.assertEqual(self.check([], [])["result"], "INVALID")

    def test_invalid_status_and_declaration(self):
        for state in ("", "NOT PASS", "PASS / UNKNOWN"):
            with self.subTest(state=state):
                self.assertEqual(self.check(["a"], [row("a", state)])["result"], "INVALID")
        with self.assertRaises(ValueError):
            mod.reconcile(candidates("a"), report([row("a")], "NOT COMPLETE"))

    def test_unresolved_scope_must_remain_unknown(self):
        ledger = [{"id": "scope", "source": "dynamic route", "kind": "unresolved_scope"}]
        for state in ("PASS", "FAIL", "N/A", "OUT_OF_SCOPE"):
            with self.subTest(state=state):
                self.assertEqual(mod.reconcile(ledger, report([row("scope", state)]))["result"], "INVALID")
        self.assertEqual(mod.reconcile(ledger, report([row("scope", "UNKNOWN")], "PARTIAL"))["result"], "PARTIAL")

    def test_resolved_scope_exact_mapping_order_independent(self):
        ledger = candidates("a", "b") + [
            {"id": "scope", "source": "route", "kind": "resolved_scope", "resolved_to": ["a", "b"]}]
        rows = [row("a"), row("b"), row("scope", "N/A", '["b","a"]', "EV-001")]
        self.assertEqual(mod.reconcile(ledger, report(rows))["result"], "COMPLETE")
        for mapping in ("-", '["a"]', '["a","z"]', '["a","a","b"]', "a,b", "[7]", "null"):
            with self.subTest(mapping=mapping):
                self.assertEqual(mod.reconcile(ledger, report(rows[:2] + [row("scope", "N/A", mapping)]))["result"], "INVALID")
        self.assertEqual(mod.reconcile(ledger, report(rows[:2]))["result"], "INVALID")
        self.assertEqual(mod.reconcile(ledger, report([row("a", "UNKNOWN"), *rows[1:]], "PARTIAL"))["result"], "PARTIAL")

    def test_invalid_resolved_targets(self):
        for targets in ([], ["missing"], ["scope"], ["a", "a"], [7], [{}], None):
            with self.subTest(targets=targets):
                ledger = candidates("a") + [
                    {"id": "scope", "source": "route", "kind": "resolved_scope", "resolved_to": targets}]
                self.assertEqual(mod.reconcile(ledger, report([row("a"), row("scope", "N/A", '["a"]')]))["result"], "INVALID")

    def test_non_scope_cannot_supply_mapping(self):
        self.assertEqual(self.check(["a"], [row("a", mapping='["a"]')])["result"], "INVALID")

    def test_exclusion_is_an_ai_decision(self):
        r = self.check(["a", "b"], [row("a", "N/A", detail="EV-001 not applicable"),
                                   row("b", "OUT_OF_SCOPE", detail="EV-002 user boundary")])
        self.assertEqual(r["result"], "COMPLETE")

    def test_invalid_candidate_input(self):
        for item in ({"id": "a"}, {"id": " a", "source": "s"}, {"id": "a|b", "source": "s"},
                     {"id": "a", "source": " "}, {"id": "a", "source": "s", "kind": "wrong"}):
            with self.subTest(item=item):
                self.assertEqual(mod.reconcile([item], report([]))["result"], "INVALID")
        with self.assertRaises(ValueError):
            mod.reconcile({}, report([]))

    def test_fixed_table_shape(self):
        md = report([row("a")])
        for bad in ("| a | PASS | - |", "a | PASS | - | note", "| a | PASS | - | note | extra |"):
            with self.subTest(bad=bad):
                altered = md.replace("| a | PASS | - | CHK-001 EV-001 |", bad)
                self.assertEqual(mod.reconcile(candidates("a"), altered)["result"], "INVALID")
        for bad in ("no table", md + "\n### 覆盖对账\n", md.replace("|---|---|---|---|", "|---|---|---|")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    mod.reconcile(candidates("a"), bad)

    def test_other_markdown_and_evidence_not_parsed(self):
        md = report([row("a", detail="[source](https://example.org/CHK-001/EV-001)")])
        # COMPLETE is only structural reconciliation. AI must still check the actual evidence.
        md += "\n<!-- hidden example -->\n[](https://example.org)\n<https://example.org>\n"
        self.assertEqual(mod.reconcile(candidates("a"), md)["result"], "COMPLETE")

    def test_cli_actual_report_and_invalid_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, md = Path(tmp) / "ledger.json", Path(tmp) / "impact-analysis.md"
            ledger.write_text(json.dumps(candidates("a", "b")), encoding="utf-8")
            md.write_text(report([row("a")]), encoding="utf-8")
            run = subprocess.run([sys.executable, "-B", str(TOOL), str(ledger), str(md)],
                                 capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(run.returncode, 1)
            self.assertEqual(json.loads(run.stdout)["missing"], ["b"])


if __name__ == "__main__":
    unittest.main()
