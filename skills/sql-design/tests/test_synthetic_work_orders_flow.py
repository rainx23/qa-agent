"""P3 single-query multi-scenario synthetic design; no database connection or SQL execution."""
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
P1_TOOLS = HERE.parents[1] / "testcase-design" / "tools"
sys.path.insert(0, str(P1_TOOLS))
import manifest  # noqa: E402

SQL_FILE = FIXTURES / "synthetic-work-orders.sql"
DESIGN_FILE = FIXTURES / "synthetic-work-orders.md"
ROLE_BY_ID = {
    "SQL-01": ("sql-design", "sql-design.sql"),
}


def read_blocks():
    sql = SQL_FILE.read_text(encoding="utf-8")
    heads = list(re.finditer(r"(?m)^-- (SQL-\d{2}) \|", sql))
    blocks = {}
    for index, match in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(sql)
        blocks[match.group(1)] = sql[match.start():end].strip()
    return sql, blocks


def parse_markdown_table(markdown, header):
    lines = markdown.splitlines()
    pos = lines.index(header)
    items = []
    for line in lines[pos + 2:]:
        if not line.startswith("|"):
            break
        items.append([x.strip() for x in line.strip().strip("|").split("|")])
    return items


class SyntheticWorkOrdersTests(unittest.TestCase):
    def test_oracle_arithmetic_from_fixture_only(self):
        """Deterministic check of authored synthetic data, not a SQL execution."""
        md = DESIGN_FILE.read_text(encoding="utf-8")
        orders = parse_markdown_table(
            md, "| order_id | group_code | state | is_deleted | amount |")
        events = parse_markdown_table(
            md, "| event_id | order_id | event_type |")
        eligible = {
            order_id: (group_code, int(amount))
            for order_id, group_code, state, deleted, amount in orders
            if state == "CLOSED" and deleted == "0"
        }
        groups = defaultdict(lambda: {"orders": set(), "amount": 0, "events": 0})
        for order_id, (group, amount) in eligible.items():
            groups[group]["orders"].add(order_id)
            groups[group]["amount"] += amount
        for _, order_id, _ in events:
            if order_id in eligible:
                groups[eligible[order_id][0]]["events"] += 1
        actual = {
            group: (len(v["orders"]), v["amount"],
                    v["amount"] / len(v["orders"]), v["events"])
            for group, v in groups.items()
        }
        self.assertEqual(actual, {"A": (2, 150, 75.0, 3), "B": (1, 60, 60.0, 3)})
        # A naive event join would inflate group A's amount 150 -> 250
        event_counts = Counter(order_id for _, order_id, _ in events)
        naive_amount_a = sum(
            amount * event_counts[order_id]
            for order_id, (group, amount) in eligible.items()
            if group == "A"
        )
        self.assertEqual(naive_amount_a, 250)

    def test_coverage_evidence_and_unknown_filter_are_not_faked(self):
        md = DESIGN_FILE.read_text(encoding="utf-8")
        sql, blocks = read_blocks()
        self.assertEqual(set(blocks), {"SQL-01"})
        for marker in ("VP-01", "VP-02", "VP-03", "VP-04",
                       "SIM-TC-01", "SIM-TC-02", "SIM-TC-03", "SIM-TC-04",
                       "F", "V", "F+V", "N", "UNKNOWN", "NOT_RUN",
                       "NOT_VERIFIED", "SQL-01"):
            self.assertIn(marker, md)
        self.assertIn("team_scope = UNKNOWN", md)
        sql_body = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.S)
        self.assertNotIn("team_scope", sql_body)
        self.assertIn("is_deleted = 0", sql)
        self.assertIn("SQL-01", sql)

    def test_sql_static_contract_and_grain_isolation(self):
        sql, blocks = read_blocks()
        self.assertEqual(set(blocks), {"SQL-01"})
        self.assertEqual(sql.count(";"), 1)
        block = blocks["SQL-01"]
        no_comments = re.sub(r"/\*.*?\*/|--[^\n]*", "", block, flags=re.S)
        self.assertTrue(no_comments.lstrip().lower().startswith("with v_"))
        self.assertTrue(no_comments.strip().endswith(";"))
        self.assertIn("t1.state = 'CLOSED'", no_comments)
        self.assertIn("t1.is_deleted = 0", no_comments)
        self.assertNotRegex(
            no_comments.lower(),
            r"\b(insert|update|delete|drop|alter|truncate|merge|create)\b",
        )
        self.assertNotRegex(no_comments.lower(), r"\bselect\s+\*")
        self.assertIn("row_number() over", no_comments.lower())
        self.assertIn("where t1.sample_rank = 1", no_comments.lower())
        self.assertIn("count(distinct t1.order_id)", no_comments.lower())
        self.assertIn("sum(t1.amount)", no_comments.lower())
        self.assertIn("count(t1.event_id)", no_comments.lower())
        self.assertIn("v_group_metrics", no_comments)
        self.assertIn("v_selected_samples", no_comments)
        self.assertIn("limit 100", no_comments.lower())
        self.assertIn("-- 模拟页面可查询的工单 ID", block)
        self.assertIn("-- 独立预期：业务组工单平均金额", block)
        projection = re.search(r"(?is)\nselect\n(.*?)\nfrom ", block)
        self.assertIsNotNone(projection)
        for output_line in projection.group(1).splitlines():
            if output_line.strip():
                self.assertIn("--", output_line)

    def test_synthetic_sql_to_manifest_and_incremental_role(self):
        """Publish one SQL query plus scenario coverage to a system temp directory."""
        sql, blocks = read_blocks()
        file_header = sql.split("-- SQL-01 |", 1)[0]
        self.assertIn("author: Rainx", file_header)
        self.assertIn("create time:", file_header)
        self.assertIn("database:", file_header)
        self.assertIn("execution_engine:", file_header)
        self.assertIn("sql_dialect:", file_header)

        with tempfile.TemporaryDirectory(prefix="p3-synthetic-e2e-") as tmp:
            root = Path(tmp) / "996004-P3-synthetic"
            staging = Path(tmp) / "staging"
            staging.mkdir()
            md = DESIGN_FILE.read_text(encoding="utf-8")
            coverage_section = md.split(
                "## 3. 场景识别、合并与可追溯性", 1)[1].split("## 4.", 1)[0]
            scenario_path = staging / "scenario-coverage.md"
            scenario_path.write_text(
                "# 场景清单\n\n" + coverage_section.strip() + "\n",
                encoding="utf-8",
            )
            original = {"scenario-coverage": scenario_path}
            for block_id, block in blocks.items():
                role, filename = ROLE_BY_ID[block_id]
                path = staging / filename
                path.write_text(file_header + block + "\n", encoding="utf-8")
                original[role] = path

            items = [
                {"category": "sql", "role": role,
                 "path": "sql/" + path.name, "source_path": str(path)}
                for role, path in original.items()
            ]
            now = datetime.now(timezone(timedelta(hours=8))).replace(microsecond=0)
            first = manifest.publish_version(
                root, "996004", "P3-synthetic", items,
                created_at=now.isoformat(), expected_base_version=None)
            self.assertEqual(first["version_id"], now.strftime("%Y%m%d") + "-v1")
            self.assertEqual(first["manifest"]["schema_version"], "1")
            self.assertEqual(first["manifest"]["case_snapshot"], [])
            first_sha = {
                x["role"]: x["sha256"] for x in first["manifest"]["artifacts"]
            }
            latest = first["version_id"]

            # The hypothetical revision affects only event-count semantics.
            revised = original["sql-design"]
            text = revised.read_text(encoding="utf-8")
            self.assertIn("count(t1.event_id)", text)
            revised.write_text(
                text.replace("count(t1.event_id)", "count(distinct t1.event_id)"),
                encoding="utf-8")
            next_items = [{
                "category": "sql", "role": "sql-design",
                "path": "sql/sql-design.sql", "source_path": str(revised)
            }]
            second = manifest.publish_version(
                root, "996004", "P3-synthetic", next_items,
                created_at=(now + timedelta(seconds=1)).isoformat(),
                expected_base_version=latest)
            carried = {x["role"]: x for x in second["manifest"]["artifacts"]}
            self.assertEqual(second["version_id"], now.strftime("%Y%m%d") + "-v2")
            self.assertEqual(
                carried["scenario-coverage"]["source_version"], latest)
            self.assertEqual(
                carried["scenario-coverage"]["sha256"],
                first_sha["scenario-coverage"])
            self.assertEqual(carried["scenario-coverage"]["change"], "unchanged")
            self.assertFalse(
                (root / second["version_id"] / "sql" / "scenario-coverage.md").exists()
            )
            self.assertEqual(
                carried["sql-design"]["source_version"], second["version_id"])
            self.assertNotEqual(
                carried["sql-design"]["sha256"], first_sha["sql-design"])
            with redirect_stdout(io.StringIO()) as capture:
                code = manifest.main(["validate", str(root)])
            self.assertEqual(code, 0, capture.getvalue())
            self.assertEqual(json.loads(capture.getvalue())["result"],
                             "MANIFEST_HISTORY_PASS")
        self.assertFalse(Path(tmp).exists())


if __name__ == "__main__":
    unittest.main()
