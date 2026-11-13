"""P3 SQL 只读 CTE 作用域检查回归。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_sql_structure import find_scope_issues


class SqlScopeTests(unittest.TestCase):
    def test_bad_reuse_is_detected(self):
        sql = "-- SQL-01\nwith v_a as (select 1) select * from v_a;\n-- SQL-02\nselect * from v_a;\n"
        self.assertEqual(find_scope_issues(sql), [("SQL-02", 4, "v_a")])

    def test_second_cte_in_same_statement_must_not_leak(self):
        sql = "-- SQL-01\nwith v_param as (select 1), v_trunk as (select * from v_param) select * from v_trunk;\n-- SQL-02\nselect * from v_trunk;"
        self.assertEqual(find_scope_issues(sql), [("SQL-02", 4, "v_trunk")])

    def test_label_uses_block_heading_not_body_reference(self):
        sql = "-- SQL-01\nwith v_a as (select 1) select * from v_a;\n-- SQL-02\n-- 后续 SQL-03 可做业务对照\nselect * from v_a;"
        self.assertEqual(find_scope_issues(sql), [("SQL-02", 5, "v_a")])

    def test_compact_comma_cte_leak_is_detected(self):
        sql = "-- SQL-01\nwith v_p as (select 1),v_a as (select 2) select * from v_a;\n-- SQL-02\nselect * from v_a;"
        self.assertEqual(find_scope_issues(sql), [("SQL-02", 4, "v_a")])

    def test_compact_comma_redeclaration_is_valid(self):
        sql = "with v_a as (select 1) select * from v_a;\nwith v_p as (select 2),v_a as (select 3) select * from v_a;"
        self.assertEqual(find_scope_issues(sql), [])

    def test_qualified_relation_is_not_cte(self):
        sql = "with v_a as (select 1 as n) select n from v_a;\nselect n from v_a.real_table;"
        self.assertEqual(find_scope_issues(sql), [])

    def test_qualified_relation_with_whitespace_is_not_cte(self):
        sql = "with v_a as (select 1 as n) select n from v_a;\nselect n from v_a . real_table;"
        self.assertEqual(find_scope_issues(sql), [])

    def test_repeat_definition_is_valid(self):
        sql = "with v_a as (select 1) select * from v_a;\nwith v_a as (select 2) select * from v_a;"
        self.assertEqual(find_scope_issues(sql), [])

    def test_semicolons_inside_comments_and_strings(self):
        sql = "-- ; from v_a\nwith v_a as (select ';' as x) select * from v_a;\n/* ; */\nwith v_a as (select 2) select * from v_a;"
        self.assertEqual(find_scope_issues(sql), [])

    def test_existing_synthetic_sql(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "synthetic-work-orders.sql"
        self.assertEqual(find_scope_issues(fixture.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
