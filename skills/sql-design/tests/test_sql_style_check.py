"""P3 SQL CTE 声明排版检查：不改变语法、业务计算或 SQL-only 发布。"""
from contextlib import redirect_stdout
from pathlib import Path
import io
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
from check_sql_style import check_ctes, main, mask_non_code


class SqlCteLayoutTests(unittest.TestCase):
    @staticmethod
    def issues(sql):
        result = []
        check_ctes(mask_non_code(sql), sql, result)
        return result

    def assert_layout_error(self, sql):
        issues = self.issues(sql)
        self.assertTrue(any("CTE 声明必须在同一行" in msg for _, msg in issues), issues)

    def test_first_cte_same_line(self):
        self.assertEqual(self.issues("with v_a as (select 1) select 1;"), [])

    def test_first_cte_newline_is_rejected(self):
        self.assert_layout_error("with\nv_a as (select 1) select 1;")

    def test_first_cte_as_newline_is_rejected(self):
        self.assert_layout_error("with v_a\nas (select 1) select 1;")

    def test_first_cte_open_parenthesis_newline_is_rejected(self):
        self.assert_layout_error("with v_a as\n(select 1) select 1;")

    def test_following_cte_comma_can_start_new_line(self):
        sql = "with v_a as (select 1)\n, v_b as (select 2) select 1;"
        self.assertEqual(self.issues(sql), [])

    def test_following_cte_newline_after_comma_is_rejected(self):
        self.assert_layout_error("with v_a as (select 1)\n,\nv_b as (select 2) select 1;")

    def test_following_cte_newline_before_as_is_rejected(self):
        self.assert_layout_error("with v_a as (select 1)\n, v_b\nas (select 2) select 1;")

    def test_following_cte_open_parenthesis_newline_is_rejected(self):
        self.assert_layout_error("with v_a as (select 1)\n, v_b as\n(select 2) select 1;")

    def test_explicit_column_list_and_recursive(self):
        self.assertEqual(self.issues("with recursive v_a(id) as (select 1) select 1;"), [])
        self.assert_layout_error("with recursive\nv_a(id) as (select 1) select 1;")
        self.assert_layout_error("with v_a(id,\ncode) as (select 1) select 1;")

    def test_nested_cte_declaration_is_checked(self):
        self.assert_layout_error("select 1 from (with\nv_inner as (select 1) select 1) t1;")

    def test_string_and_comment_are_not_cte_declarations(self):
        sql = (
            "-- with\\nv_fake as (\n"
            "select 'with\nv_fake as (' as content, 1 as n;\n"
            "/* with\nv_fake as ( */\n"
        )
        self.assertEqual(self.issues(sql), [])

    def test_existing_v_prefix_rule_is_preserved(self):
        self.assertTrue(
            any("必须使用 v_ 前缀" in msg
                for _, msg in self.issues("with bad_cte as (select 1) select 1;"))
        )

    def test_realistic_fixture_cli_pass_and_regression_fail(self):
        sql = (HERE / "fixtures" / "synthetic-work-orders.sql").read_text(encoding="utf-8")
        self.assertIn("with v_valid_orders as (", sql)
        with tempfile.TemporaryDirectory(prefix="p3-cte-style-") as folder:
            path = Path(folder) / "case.sql"
            output = io.StringIO()
            path.write_text(sql, encoding="utf-8")
            with redirect_stdout(output):
                passed = main(["check_sql_style.py", str(path)])
            self.assertEqual(passed, 0, output.getvalue())

            path.write_text(sql.replace("with v_valid_orders as (",
                                        "with\nv_valid_orders as (", 1), encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                failed = main(["check_sql_style.py", str(path)])
            self.assertEqual(failed, 1, output.getvalue())
            self.assertIn("CTE 声明必须在同一行", output.getvalue())


if __name__ == "__main__":
    unittest.main()
