"""Read-only platform payload mapping tests."""
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import platform_payloads as payloads


MARKDOWN = """# 999999｜示例需求

## 一、核心业务
### 验证查询结果
<!-- qa_case_id: QA-999999-0123456789 -->
- **优先级**：P1
- **前置条件**：存在可查询数据
- **测试数据**：客户A及2025年1月数据
1. **操作**：进入销售结果页面，选择客户A并查询
   - **预期**：只展示客户A的数据
   - **预期**：汇总值与列表口径一致
2. **操作**：清空客户条件并查询
   - **预期**：恢复默认查询范围

## 二、异常场景
### 无数据时展示空结果
<!-- qa_case_id: QA-999999-abcdef1234 -->
- **优先级**：P2
1. **操作**：选择无匹配数据的条件并查询
   - **预期**：列表展示空结果
"""



ACE_TARGET = {
    "product_id": 123,
    "dir_id": 456,
    "project_id": "789",
    "project_name": "测试迭代",
    "story_id": "999999",
    "story_name": "示例需求",
}


class PlatformPayloadTests(unittest.TestCase):
    def test_preview_is_read_only_and_one_request_per_case(self):
        result = payloads.build_zentao_preview(MARKDOWN, 999999)
        self.assertEqual(result["status"], "PREVIEW_ONLY")
        self.assertFalse(result["write_ready"])
        self.assertFalse(result["platform_sent"])
        self.assertEqual(result["transport_mode"], "ONE_CASE_PER_MCP_CALL")
        self.assertFalse(result["bulk_api_available"])
        self.assertEqual(result["case_count"], 2)
        self.assertEqual(len(result["requests"]), 2)
        self.assertEqual(result["requests"][0]["request"]["type"], "feature")

    def test_case_identity_is_separate_from_platform_request(self):
        result = payloads.build_zentao_preview(MARKDOWN, 999999)
        first = result["requests"][0]
        self.assertEqual(first["case_id"], "QA-999999-0123456789")
        self.assertNotIn("case_id", first["request"])
        self.assertEqual(first["request"]["story"], 999999)

    def test_all_steps_and_multiple_expectations_are_preserved(self):
        result = payloads.build_zentao_preview(MARKDOWN, 999999)
        request = result["requests"][0]["request"]
        self.assertEqual(len(request["stepList"]), 2)
        self.assertEqual(
            request["stepList"][0]["expectResult"],
            "只展示客户A的数据\n汇总值与列表口径一致",
        )
        self.assertEqual(request["stepList"][1]["stepDesc"], "清空客户条件并查询")

    def test_precondition_and_test_data_are_not_dropped(self):
        result = payloads.build_zentao_preview(MARKDOWN, 999999)
        precondition = result["requests"][0]["request"]["precondition"]
        self.assertEqual(
            precondition,
            "存在可查询数据\n测试数据：客户A及2025年1月数据",
        )
        self.assertNotIn("前置条件：", precondition)

    def test_priority_candidate_is_explicit_and_p1_maps_to_two(self):
        result = payloads.build_zentao_preview(MARKDOWN, 999999)
        self.assertEqual(result["requests"][0]["request"]["pri"], 2)
        self.assertEqual(result["requests"][1]["request"]["pri"], 3)
        self.assertEqual(
            result["priority_mapping_status"],
            "HISTORICAL_CANDIDATE_NOT_FULLY_VERIFIED",
        )
        self.assertIn(
            "PRIORITY_MAPPING_REQUIRES_CURRENT_PLATFORM_VERIFICATION",
            result["warnings"],
        )


    def test_requirement_mismatch_blocks_preview(self):
        with self.assertRaisesRegex(payloads.PlatformPayloadError, "DOES_NOT_MATCH"):
            payloads.build_zentao_preview(MARKDOWN, 900106)

    def test_invalid_story_id_blocks_preview(self):
        with self.assertRaisesRegex(payloads.PlatformPayloadError, "STORY_ID_INVALID"):
            payloads.build_zentao_preview(MARKDOWN, "0")

    def test_unicode_and_long_text_are_not_truncated(self):
        long_text = "业务结果" * 200
        markdown = MARKDOWN.replace("只展示客户A的数据", long_text)
        result = payloads.build_zentao_preview(markdown, 999999)
        self.assertEqual(
            result["requests"][0]["request"]["stepList"][0]["expectResult"].split("\n")[0],
            long_text,
        )



    def test_ace_preview_builds_one_requirement_mindmap_with_six_context_fields(self):
        result = payloads.build_ace_preview(MARKDOWN, ACE_TARGET)
        self.assertEqual(result["status"], "PREVIEW_ONLY")
        self.assertFalse(result["write_ready"])
        self.assertFalse(result["platform_sent"])
        self.assertEqual(result["transport_mode"], "ONE_MINDMAP_PER_REQUIREMENT")
        self.assertEqual((result["group_count"], result["case_count"]), (2, 2))
        request = result["request"]
        self.assertEqual(
            {key: request[key] for key in (
                "product_id", "dir_id", "project_id", "project_name",
                "story_id", "story_name"
            )},
            ACE_TARGET,
        )
        self.assertEqual(request["title"], "示例需求")
        self.assertEqual(request["data"]["data"]["text"], "示例需求")

    def test_ace_preview_preserves_groups_cases_steps_and_all_expected_nodes(self):
        result = payloads.build_ace_preview(MARKDOWN, ACE_TARGET)
        root = result["request"]["data"]
        first_group, second_group = root["children"]
        self.assertEqual(first_group["data"]["text"], "一、核心业务")
        self.assertEqual(second_group["data"]["text"], "二、异常场景")

        first_case = first_group["children"][0]
        self.assertEqual(first_case["data"]["text"], "验证查询结果")
        self.assertEqual(first_case["data"]["tag"], [{"text": "标题"}])
        self.assertEqual(first_case["data"]["icon"], ["priority_2"])
        self.assertEqual(
            [node["data"]["text"] for node in first_case["children"]],
            [
                "前置条件：存在可查询数据",
                "测试数据：客户A及2025年1月数据",
                "步骤 1：进入销售结果页面，选择客户A并查询",
                "步骤 2：清空客户条件并查询",
            ],
        )
        first_step = first_case["children"][2]
        self.assertEqual(
            [node["data"]["text"] for node in first_step["children"]],
            ["预期：只展示客户A的数据", "预期：汇总值与列表口径一致"],
        )
        second_case = second_group["children"][0]
        self.assertEqual(second_case["data"]["icon"], ["priority_3"])
        self.assertEqual(len(second_case["children"]), 1)
        self.assertEqual(
            second_case["children"][0]["data"]["text"],
            "步骤 1：选择无匹配数据的条件并查询",
        )

    def test_ace_preview_uses_stable_unique_uids_without_visible_case_ids(self):
        first = payloads.build_ace_preview(MARKDOWN, ACE_TARGET)
        second = payloads.build_ace_preview(MARKDOWN, ACE_TARGET)
        self.assertEqual(first["request"], second["request"])

        nodes = []
        def walk(node):
            nodes.append(node)
            for child in node["children"]:
                walk(child)
        walk(first["request"]["data"])
        uids = [node["data"]["uid"] for node in nodes]
        self.assertEqual(len(uids), len(set(uids)))
        self.assertTrue(all(uids))
        visible_text = [node["data"]["text"] for node in nodes]
        self.assertFalse(any("QA-999999-" in text for text in visible_text))
        self.assertEqual(
            first["case_mapping"][0]["case_id"],
            "QA-999999-0123456789",
        )

    def test_ace_priority_mapping_uses_current_configured_mapping(self):
        result = payloads.build_ace_preview(MARKDOWN, ACE_TARGET)
        self.assertEqual(
            result["priority_mapping_status"],
            "CONFIGURED_MAPPING_IN_USE",
        )
        self.assertEqual(
            result["priority_mapping"],
            {"P0": "priority_1", "P1": "priority_2", "P2": "priority_3",
             "P3": "priority_4", "P4": "priority_5"},
        )
        self.assertEqual(result["warnings"], ["PREVIEW_ONLY_NO_PLATFORM_WRITE"])

    def test_ace_target_requirement_identity_must_match_markdown(self):
        bad_id = dict(ACE_TARGET, story_id="900106")
        with self.assertRaisesRegex(
            payloads.PlatformPayloadError, "STORY_ID_DOES_NOT_MATCH"
        ):
            payloads.build_ace_preview(MARKDOWN, bad_id)
        bad_name = dict(ACE_TARGET, story_name="其他需求")
        with self.assertRaisesRegex(
            payloads.PlatformPayloadError, "STORY_NAME_DOES_NOT_MATCH"
        ):
            payloads.build_ace_preview(MARKDOWN, bad_name)

    def test_ace_requires_all_six_real_target_fields(self):
        for field in (
            "product_id", "dir_id", "project_id", "project_name",
            "story_id", "story_name"
        ):
            target = dict(ACE_TARGET)
            target.pop(field)
            with self.subTest(field=field):
                with self.assertRaises(payloads.PlatformPayloadError):
                    payloads.build_ace_preview(MARKDOWN, target)

    def test_ace_does_not_truncate_long_source_text(self):
        long_text = "业务操作" * 200
        markdown = MARKDOWN.replace(
            "进入销售结果页面，选择客户A并查询", long_text
        )
        result = payloads.build_ace_preview(markdown, ACE_TARGET)
        step = result["request"]["data"]["children"][0]["children"][0]["children"][2]
        self.assertTrue(step["data"]["text"].endswith(long_text))

if __name__ == "__main__":
    unittest.main()
