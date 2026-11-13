"""Bounded deterministic tests for the first P1 artifact batch."""
import copy
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "tools" / "artifacts.py"
spec = importlib.util.spec_from_file_location("p1_artifacts", TOOL)
art = importlib.util.module_from_spec(spec)
spec.loader.exec_module(art)

MD = """# 900661｜示例需求

## 一、核心业务
### 页面筛选后显示符合条件的结果
<!-- qa_case_id: QA-900661-0123456789 -->
- **优先级**：P1
- **前置条件**：存在符合条件的数据
1. **操作**：进入业务页面，选择筛选条件并查询
   - **预期**：列表仅展示符合筛选条件的数据
   - **预期**：汇总结果按当前筛选条件计算
2. **操作**：清空筛选条件并重新查询
   - **预期**：恢复默认范围的结果

## 二、异常场景
### 无匹配数据时提示空结果
<!-- qa_case_id: QA-900661-abcdef1234 -->
- **优先级**：P2
- **测试数据**：选择无匹配记录的条件
1. **操作**：在业务页面输入无匹配的条件并查询
   - **预期**：列表显示空结果，不保留上次记录

## 附录：设计依据
- 来源来自示例文本，此处不参与 XMind 展示
"""
ORACLE = {
    "schema_version": "1",
    "requirement": {"id": "900661", "name": "示例需求"},
    "sources": [{"id": "S1", "description": "示例需求正文", "locator": "需求900661-正文"}],
    "obligations": [
        {
            "id": "O1", "source_ids": ["S1"], "rule": "查询按筛选条件返回数据",
            "expected_outcome": "结果范围受当前条件约束", "certainty": "confirmed"
        },
        {
            "id": "O2", "source_ids": ["S1"], "rule": "无匹配数据时展示空状态",
            "expected_outcome": "不残留上次结果", "certainty": "inferred"
        }
    ],
    "open_questions": [{"source_ids": ["S1"], "question": "是否需要空状态文案？", "impact": "文案断言待确认"}]
}


class ArtifactTests(unittest.TestCase):
    def test_valid_pair_and_independent_counts(self):
        report = art.check_pair(MD, ORACLE)
        self.assertEqual((report["group_count"], report["case_count"], report["step_count"]), (2, 2, 3))
        self.assertEqual((report["oracle_obligations"], report["open_questions"]), (2, 1))
        self.assertEqual(report["semantic_review"], "NOT_AUTOMATED")

    def test_text_not_truncated(self):
        long_text = "结果" * 260
        content = MD.replace("列表仅展示符合筛选条件的数据", long_text)
        self.assertEqual(art.parse_markdown(content)["groups"][0]["cases"][0]["steps"][0]["expected"][0], long_text)

    def test_duplicate_id(self):
        content = MD.replace("QA-900661-abcdef1234", "QA-900661-0123456789")
        with self.assertRaisesRegex(art.ArtifactError, "重复"):
            art.parse_markdown(content)

    def test_wrong_requirement_id_in_case(self):
        with self.assertRaisesRegex(art.ArtifactError, "需求编号不一致"):
            art.parse_markdown(MD.replace("QA-900661-abcdef1234", "QA-123456-abcdef1234"))

    def test_missing_identity_blocks(self):
        with self.assertRaisesRegex(art.ArtifactError, "缺少内部 Case ID"):
            art.parse_markdown(MD.replace("<!-- qa_case_id: QA-900661-abcdef1234 -->", ""))

    def test_id_must_directly_follow_title(self):
        moved = MD.replace(
            "<!-- qa_case_id: QA-900661-0123456789 -->\n- **优先级**：P1",
            "- **优先级**：P1\n<!-- qa_case_id: QA-900661-0123456789 -->",
        )
        with self.assertRaisesRegex(art.ArtifactError, "紧跟标题"):
            art.parse_markdown(moved)

    def test_missing_expected_blocks(self):
        content = MD.replace("   - **预期**：恢复默认范围的结果", "")
        with self.assertRaisesRegex(art.ArtifactError, "没有预期"):
            art.parse_markdown(content)

    def test_step_order_blocks(self):
        content = MD.replace("2. **操作**：清空", "3. **操作**：清空")
        with self.assertRaisesRegex(art.ArtifactError, "连续编号"):
            art.parse_markdown(content)

    def test_unknown_markdown_fails_closed(self):
        with self.assertRaisesRegex(art.ArtifactError, "未知结构"):
            art.parse_markdown(MD.replace("- **优先级**：P1", "- **优先级**：P1\n未经识别的正文"))

    def test_priority_out_of_range(self):
        with self.assertRaisesRegex(art.ArtifactError, "P0–P4"):
            art.parse_markdown(MD.replace("- **优先级**：P1", "- **优先级**：P5"))

    def test_appendix_before_later_group_fails_not_silently_omits(self):
        content = MD.replace(
            "## 二、异常场景",
            "## 附录：设计依据\n- 中间出现了不合法的附录\n\n## 二、异常场景",
        )
        with self.assertRaisesRegex(art.ArtifactError, "附录之后"):
            art.parse_markdown(content)

    def test_business_group_named_appendix_query_is_not_appendix(self):
        content = MD.replace("## 二、异常场景", "## 附录查询业务")
        parsed = art.parse_markdown(content)
        self.assertEqual(len(parsed["groups"]), 2)
        self.assertEqual(parsed["groups"][1]["name"], "附录查询业务")

    def test_case_structure_inside_terminal_appendix_is_rejected(self):
        appendix = "## 附录：设计依据\n- 来源来自示例文本，此处不参与 XMind 展示\n"
        for injected in (
            "### 漏写到附录的用例",
            "<!-- qa_case_id: QA-900661-fedcba9876 -->",
            "- **优先级**：P2",
            "1. **操作**：查询页面",
            "   - **预期**：显示结果",
            "## 新的业务分组",
            "#### 附录再增加标题",
        ):
            with self.subTest(injected=injected):
                with self.assertRaisesRegex(art.ArtifactError, "附录之后"):
                    art.parse_markdown(MD.replace(appendix, appendix + injected + "\n"))

    def test_terminal_appendix_prose_is_allowed(self):
        parsed = art.parse_markdown(MD + "\n- 问题：应保留业务义务\n备注文本\n")
        self.assertEqual(sum(len(g["cases"]) for g in parsed["groups"]), 2)

    def test_oracle_certainty_invalid_types_fail_cleanly(self):
        for bad in ([], {}, ["confirmed"], {"value": "confirmed"}, 1, None):
            data = copy.deepcopy(ORACLE)
            data["obligations"][0]["certainty"] = bad
            with self.subTest(value=bad):
                with self.assertRaisesRegex(art.ArtifactError, "certainty"):
                    art.validate_oracle(data)

    def test_cli_json_is_gbk_safe_and_unicode_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "testcases.md"
            oracle = Path(tmp) / "oracle.json"
            md.write_text(MD.replace("示例需求", "示例🙂需求"), encoding="utf-8")
            data = copy.deepcopy(ORACLE)
            data["requirement"]["name"] = "示例🙂需求"
            oracle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            output = io.BytesIO()
            stream = io.TextIOWrapper(output, encoding="gbk", errors="strict")
            with patch.object(art.sys, "stdout", stream):
                code = art.main([str(md), str(oracle)])
                stream.flush()
            self.assertEqual(code, 0)
            decoded = output.getvalue().decode("gbk")
            self.assertTrue(decoded.isascii())
            self.assertEqual(json.loads(decoded)["requirement"]["name"], "示例🙂需求")
            md.write_text(MD.replace("无匹配数据时提示空结果", "无匹配🙂数据")
                          .replace("   - **预期**：列表显示空结果，不保留上次记录", ""),
                          encoding="utf-8")
            output2 = io.BytesIO()
            stream2 = io.TextIOWrapper(output2, encoding="gbk", errors="strict")
            with patch.object(art.sys, "stdout", stream2):
                code = art.main([str(md), str(oracle)])
                stream2.flush()
            self.assertEqual(code, 1)
            self.assertTrue(output2.getvalue().decode("gbk").isascii())
            self.assertIn("无匹配🙂数据", json.loads(output2.getvalue().decode("gbk"))["error"])

    def test_oracle_unknown_source(self):
        data = copy.deepcopy(ORACLE)
        data["obligations"][0]["source_ids"] = ["S404"]
        with self.assertRaisesRegex(art.ArtifactError, "未知来源"):
            art.validate_oracle(data)

    def test_oracle_duplicate_obligation(self):
        data = copy.deepcopy(ORACLE)
        data["obligations"][1]["id"] = "O1"
        with self.assertRaisesRegex(art.ArtifactError, "重复"):
            art.validate_oracle(data)

    def test_oracle_missing_evidence_status(self):
        data = copy.deepcopy(ORACLE)
        del data["obligations"][0]["certainty"]
        with self.assertRaisesRegex(art.ArtifactError, "certainty"):
            art.validate_oracle(data)

    def test_markdown_oracle_requirement_mismatch(self):
        data = copy.deepcopy(ORACLE)
        data["requirement"]["name"] = "不一致的需求名称"
        with self.assertRaisesRegex(art.ArtifactError, "需求编号/名称不一致"):
            art.check_pair(MD, data)

    def test_cli_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = Path(tmp) / "testcases.md"
            oracle = Path(tmp) / "oracle.json"
            md.write_text(MD, encoding="utf-8")
            oracle.write_text(json.dumps(ORACLE, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(art.main([str(md), str(oracle)]), 0)
            oracle.write_text("not json", encoding="utf-8")
            self.assertEqual(art.main([str(md), str(oracle)]), 1)


if __name__ == "__main__":
    unittest.main()
