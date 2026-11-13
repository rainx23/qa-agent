"""Unit tests for the self-contained ACE CLI adapter."""
import copy
import io
import json
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

import ace_cli
import manifest as manifest_tools
import platform_payloads
import xmind


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

TARGET = {
    "product_id": 123,
    "dir_id": 456,
    "project_id": "789",
    "project_name": "测试迭代",
    "story_id": "999999",
    "story_name": "示例需求",
}

class QueueRunner:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def completed(payload, returncode=0, stderr=""):
    return subprocess.CompletedProcess(
        args=["zero-hub-cli"], returncode=returncode,
        stdout=json.dumps(payload, ensure_ascii=False), stderr=stderr,
    )


def make_readback(preview, mind_map_id=12345, target=TARGET):
    return {
        "id": mind_map_id,
        "name": preview["request"]["title"],
        "product_id": str(target["product_id"]),
        "dir_id": target["dir_id"],
        "project_id": target["project_id"],
        "project_name": target["project_name"],
        "story_id": target["story_id"],
        "story_name": target["story_name"],
        "version": 1,
        "content": {"root": copy.deepcopy(preview["request"]["data"])},
    }


def make_mcp_readback(preview, mind_map_id=12345, target=TARGET):
    """Match the actual ACE get-mind-map metadata contract."""
    return {
        "id": mind_map_id,
        "name": preview["request"]["title"],
        "product_id": str(target["product_id"]),
        "version": 1,
        "content": {"root": copy.deepcopy(preview["request"]["data"])},
    }


_BASE_ACE_PREVIEW_BUILDER = platform_payloads.build_ace_preview


def verified_preview(markdown=MARKDOWN, target=TARGET):
    return _BASE_ACE_PREVIEW_BUILDER(markdown, target)


def verified_mapping_builder(preview=None):
    selected = preview if preview is not None else verified_preview()
    return patch.object(
        ace_cli.platform_payloads,
        "build_ace_preview",
        return_value=selected,
    )



def make_preflight_fixture(
    base_dir, markdown=MARKDOWN, target=TARGET,
    manifest_delivery_status="complete",
):
    base = Path(base_dir)
    stage = base / "stage"
    stage.mkdir(parents=True, exist_ok=True)
    markdown_path = stage / "testcases.md"
    xmind_path = stage / "testcases.xmind"
    oracle_path = stage / "oracle.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    xmind.export_xmind(markdown, xmind_path)
    oracle = {
        "schema_version": "1",
        "requirement": {"id": str(target["story_id"]), "name": str(target["story_name"])},
        "sources": [{"id": "SRC-1", "description": "需求正文", "locator": "需求正文"}],
        "obligations": [{
            "id": "OBL-1", "source_ids": ["SRC-1"], "rule": "验证核心业务结果",
            "expected_outcome": "结果符合需求", "certainty": "confirmed",
        }],
        "open_questions": [],
    }
    oracle_path.write_text(json.dumps(oracle, ensure_ascii=False), encoding="utf-8")
    requirement_root = base / "output" / (str(target["story_id"]) + "-" + str(target["story_name"]))
    staged = [
        {"category": "testcases", "role": "markdown", "path": "testcases/testcases.md", "source_path": str(markdown_path)},
        {"category": "testcases", "role": "xmind", "path": "testcases/testcases.xmind", "source_path": str(xmind_path)},
        {"category": "testcases", "role": "oracle", "path": "testcases/oracle.json", "source_path": str(oracle_path)},
    ]
    published = manifest_tools.publish_version(
        requirement_root, str(target["story_id"]), str(target["story_name"]), staged,
        delivery_status=manifest_delivery_status, created_at="2026-11-02T10:00:00+08:00",
    )
    manifest_path = Path(published["version_path"]) / "manifest.json"
    preview = verified_preview(markdown, target)
    preflight = {
        "manifest": {
            "path": str(manifest_path),
            "version_id": published["version_id"],
        },
        "target": dict(preview["target"]),
    }
    return preflight, manifest_path


class AceCliTests(unittest.TestCase):
    def setUp(self):
        self.cli_which_patch = patch.object(
            ace_cli.shutil, "which", return_value=r"C:\Tools\zero-hub-cli.exe"
        )
        self.cli_which_patch.start()
        self.addCleanup(self.cli_which_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.preflight, self.manifest_path = make_preflight_fixture(self.temp.name)

    def _patch_temp_cleanup_failure(self):
        real_temp = tempfile.TemporaryDirectory()
        self.addCleanup(real_temp.cleanup)

        class FailingTemporaryDirectory:
            def __init__(self, name):
                self.name = name

            def cleanup(self):
                raise OSError("simulated temporary-directory cleanup failure")

        return patch.object(
            ace_cli.tempfile,
            "TemporaryDirectory",
            return_value=FailingTemporaryDirectory(real_temp.name),
        )


    def test_emit_uses_ascii_safe_json_for_windows_console(self):
        stream = io.StringIO()
        with patch.object(ace_cli.sys, "stdout", stream):
            ace_cli._emit({"name": "大型演示平台"})
        output = stream.getvalue()
        self.assertIn("\\u5927", output)
        self.assertEqual(json.loads(output)["name"], "大型演示平台")

    def test_resolve_cli_uses_path_not_external_skill_path(self):
        with patch.object(ace_cli.shutil, "which", return_value=r"C:\Tools\zero-hub-cli.exe"):
            self.assertEqual(ace_cli.resolve_cli(), r"C:\Tools\zero-hub-cli.exe")

    def test_missing_cli_fails_without_guessing_a_path(self):
        with patch.object(ace_cli.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_CLI_NOT_FOUND"):
                ace_cli.resolve_cli("zero-hub-cli-not-installed")

    def test_list_projects_uses_read_only_cli_command(self):
        runner = QueueRunner(completed([{"id": 23, "name": "大型演示平台"}]))
        result = ace_cli.list_projects(runner=runner)
        self.assertEqual(result[0]["id"], 23)
        self.assertEqual(runner.calls[0][0][1:4], ["ace-testcase", "list-projects", "--json"])

    def test_directory_tree_flattens_full_paths_and_skips_virtual_root(self):
        roots = [{
            "id": 23, "name": "大型演示平台", "project_id": 23, "mind_count": 0,
            "children": [{
                "id": 271, "name": "示例业务组", "parent_id": 23, "project_id": 23,
                "children": [{
                    "id": 276, "name": "示例模块", "parent_id": 271,
                    "project_id": 23, "mind_count": 4, "children": [],
                }],
            }],
        }]
        match = ace_cli.find_directory_by_path(roots, "大型演示平台/示例业务组/示例模块")
        self.assertEqual(match["id"], 276)
        self.assertEqual(match["mind_count"], 4)
        with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_DIRECTORY_PATH_NOT_FOUND"):
            ace_cli.find_directory_by_path(roots, "示例模块")

        virtual_roots = [{
            "id": None, "isRoot": True, "name": "大型演示平台",
            "children": [{
                "id": 271, "name": "示例业务组", "parent_id": None, "project_id": 23,
                "children": [{
                    "id": 276, "name": "示例模块", "parent_id": 271,
                    "project_id": 23, "mind_count": 4, "children": [],
                }],
            }],
        }]
        self.assertEqual(
            [item["id"] for item in ace_cli.flatten_directory_tree(virtual_roots)],
            [271, 276],
        )
        self.assertEqual(
            ace_cli.find_directory_by_path(
                virtual_roots, "大型演示平台/示例业务组/示例模块"
            )["id"],
            276,
        )

    def test_directory_lookup_rejects_ambiguous_duplicate_full_paths(self):
        roots = [
            {"id": 1, "name": "项目A", "children": [{"id": 3, "name": "模块", "children": []}]},
            {"id": 2, "name": "项目A", "children": [{"id": 4, "name": "模块", "children": []}]},
        ]
        with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_DIRECTORY_PATH_AMBIGUOUS"):
            ace_cli.find_directory_by_path(roots, "项目A/模块")

    def test_get_project_directories_uses_project_id_and_returns_tree(self):
        roots = [{"id": 23, "name": "大型演示平台", "children": []}]
        runner = QueueRunner(completed(roots))
        result = ace_cli.get_project_directories(23, runner=runner)
        self.assertEqual(result[0]["id"], 23)
        self.assertEqual(
            runner.calls[0][0][1:5],
            ["ace-testcase", "project-dir", "--project-id", "23"],
        )

    def test_get_mind_map_reads_complete_content_by_known_id(self):
        payload = {
            "id": 900075, "name": "历史导图", "product_id": "23", "version": 1,
            "content": {"root": {"data": {"text": "历史导图"}, "children": []}},
        }
        runner = QueueRunner(completed(payload))
        result = ace_cli.get_mind_map(900075, runner=runner)
        self.assertEqual(result["id"], 900075)
        self.assertIn("get-mind-map", runner.calls[0][0])
        self.assertIn("--case-id", runner.calls[0][0])

    def test_extract_created_id_requires_one_unambiguous_id(self):
        self.assertEqual(
            ace_cli.extract_created_mind_map_id({
                "success": True, "data": {"mind_map_id": "900048"},
            }),
            900048,
        )
        with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_IMPORT_ID_UNRESOLVED"):
            ace_cli.extract_created_mind_map_id({"success": True, "data": {}})
        with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_IMPORT_ID_UNRESOLVED"):
            ace_cli.extract_created_mind_map_id({"id": 1, "data": {"id": 2}})

    def test_preflight_requires_explicit_write_authorization(self):
        runner = QueueRunner()
        with self.assertRaisesRegex(ace_cli.AceCliError, "ACE_WRITE_NOT_AUTHORIZED"):
            ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=False, runner=runner,
            )
        self.assertEqual(runner.calls, [])

    def test_manifest_must_be_complete_and_readable(self):
        cases = [
            ("partial", "partial", "ACE_DELIVERY_NOT_COMPLETE"),
            ("stale", None, "ACE_PREFLIGHT_MANIFEST_NOT_LATEST"),
            ("missing_path", None, "ACE_PREFLIGHT_MANIFEST_REQUIRED"),
            ("wrong_version", None, "ACE_PREFLIGHT_MANIFEST_PATH_MISMATCH"),
            ("corrupt", None, "ACE_PREFLIGHT_MANIFEST_INVALID"),
        ]
        with verified_mapping_builder():
            for name, delivery_status, expected_code in cases:
                with self.subTest(name=name):
                    preflight, manifest_path = make_preflight_fixture(
                        Path(self.temp.name) / name,
                        manifest_delivery_status=delivery_status or "complete",
                    )
                    if name == "missing_path":
                        preflight["manifest"].pop("path")
                    elif name == "stale":
                        manifest_tools.publish_version(
                            (
                                manifest_path.parent.parent.parent
                                if manifest_path.parent.parent.name == "versions"
                                else manifest_path.parent.parent
                            ),
                            "999999",
                            "示例需求",
                            [],
                            delivery_status="partial",
                            created_at="2026-11-02T11:00:00+08:00",
                            expected_base_version=preflight["manifest"]["version_id"],
                        )
                    elif name == "wrong_version":
                        preflight["manifest"]["version_id"] = "20261102-v999"
                    elif name == "corrupt":
                        manifest_path.write_text("{}", encoding="utf-8")
                    runner = QueueRunner()
                    with self.assertRaisesRegex(ace_cli.AceCliError, expected_code):
                        ace_cli.import_mind_map(
                            MARKDOWN, TARGET, preflight=preflight,
                            write_authorized=True, runner=runner,
                        )
                    self.assertEqual(runner.calls, [])

    def test_configured_priority_mapping_does_not_block_import(self):
        preview = platform_payloads.build_ace_preview(MARKDOWN, TARGET)
        self.assertEqual(
            preview["priority_mapping_status"],
            "CONFIGURED_MAPPING_IN_USE",
        )
        runner = QueueRunner(completed({"success": True, "id": 12345}))
        with verified_mapping_builder(preview):
            result = ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=True, runner=runner,
            )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertEqual(len(runner.calls), 1)
    def test_import_creates_once_and_returns_id_without_readback(self):
        preview = verified_preview(MARKDOWN, TARGET)
        import_response = {
            "success": True,
            "id": 12345,
            "url": "https://testcase.example/CaseMindMapEdit?id=12345",
        }
        runner = QueueRunner(completed(import_response))
        with verified_mapping_builder(preview):
            result = ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=True, runner=runner,
            )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertEqual(result["case_count"], 2)
        self.assertEqual(len(runner.calls), 1, "normal import must not call get-mind-map")
        import_argv = runner.calls[0][0]
        self.assertEqual(import_argv[1:3], ["ace-testcase", "import"])
        for flag, expected in (
            ("--product-id", "123"),
            ("--dir-id", "456"),
            ("--project-id", "789"),
            ("--project-name", "测试迭代"),
            ("--story-id", "999999"),
            ("--story-name", "示例需求"),
        ):
            self.assertEqual(import_argv[import_argv.index(flag) + 1], expected)
        case_path = Path(import_argv[import_argv.index("--case") + 1])
        self.assertFalse(case_path.exists(), "temporary MindNode payload must be cleaned")
        self.assertFalse(result["retry_allowed"])
    def test_mcp_create_receipt_without_success_flag_uses_id_readback(self):
        preview = verified_preview(MARKDOWN, TARGET)
        import_response = {
            "id": 12345,
            "name": preview["request"]["title"],
            "url": "https://testcase.example/CaseMindMapEdit?id=12345",
        }
        readback = make_mcp_readback(preview)
        runner = QueueRunner(completed(import_response), completed(readback))
        with verified_mapping_builder(preview):
            result = ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=True, runner=runner,
            )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertEqual(result["confirmation_method"], "ID_READBACK")
        self.assertEqual(result["readback_verification"]["content_status"], "PASS")
        self.assertEqual(
            result["readback_verification"]["association_status"], "NOT_PROVEN"
        )
        self.assertEqual(
            set(result["readback_verification"]["association_missing_fields"]),
            {"dir_id", "project_id", "project_name", "story_id", "story_name"},
        )
        self.assertEqual(len(runner.calls), 2)
        self.assertIn("get-mind-map", runner.calls[1][0])
        self.assertIn("--case-id", runner.calls[1][0])

    def test_mcp_create_receipt_readback_mismatch_returns_need_fix_with_id(self):
        preview = verified_preview(MARKDOWN, TARGET)
        readback = make_mcp_readback(preview)
        readback["content"]["root"]["children"][0]["data"]["text"] = "内容不一致"
        runner = QueueRunner(
            completed({"id": 12345, "name": preview["request"]["title"]}),
            completed(readback),
        )
        with verified_mapping_builder(preview):
            with self.assertRaises(ace_cli.AceCliError) as caught:
                ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_READBACK_MISMATCH")
        self.assertEqual(caught.exception.status, "NEED_FIX")
        self.assertEqual(caught.exception.mind_map_id, 12345)
        self.assertEqual(len(runner.calls), 2)

    def test_mcp_create_receipt_readback_failure_preserves_id_as_unknown(self):
        preview = verified_preview(MARKDOWN, TARGET)
        runner = QueueRunner(
            completed({"id": 12345, "name": preview["request"]["title"]}),
            completed({"id": 12345, "name": preview["request"]["title"]}),
        )
        with verified_mapping_builder(preview):
            with self.assertRaises(ace_cli.AceCliError) as caught:
                ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_READBACK_FAILED")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(caught.exception.mind_map_id, 12345)
        self.assertEqual(len(runner.calls), 2)


    def test_successful_create_is_preserved_when_temp_cleanup_fails(self):
        preview = verified_preview(MARKDOWN, TARGET)
        runner = QueueRunner(completed({"success": True, "id": 12345}))
        with self._patch_temp_cleanup_failure():
            with verified_mapping_builder(preview):
                result = ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertFalse(result["retry_allowed"])
        self.assertEqual(result["cleanup_warning"], "ACE_TEMP_CLEANUP_FAILED")
        self.assertEqual(result["cleanup_detail"], "OSError")
        self.assertEqual(len(runner.calls), 1)

    def test_unknown_import_outcome_is_preserved_when_temp_cleanup_fails(self):
        runner = QueueRunner(subprocess.TimeoutExpired("zero-hub-cli", 180))
        with self._patch_temp_cleanup_failure():
            with verified_mapping_builder():
                with self.assertRaises(ace_cli.AceCliError) as caught:
                    ace_cli.import_mind_map(
                        MARKDOWN, TARGET, preflight=self.preflight,
                        write_authorized=True, runner=runner,
                    )
        self.assertEqual(caught.exception.code, "ACE_CLI_TIMEOUT")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1)

    def test_rejected_import_is_preserved_when_temp_cleanup_fails(self):
        runner = QueueRunner(completed({"success": False, "code": 500}))
        with self._patch_temp_cleanup_failure():
            with verified_mapping_builder():
                with self.assertRaises(ace_cli.AceCliError) as caught:
                    ace_cli.import_mind_map(
                        MARKDOWN, TARGET, preflight=self.preflight,
                        write_authorized=True, runner=runner,
                    )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_REJECTED")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1)

    def test_nested_success_receipt_is_accepted(self):
        response = {
            "success": True,
            "data": {"success": True, "code": 0, "id": 12345},
        }
        runner = QueueRunner(completed(response))
        result = ace_cli.import_mind_map(
            MARKDOWN, TARGET, preflight=self.preflight,
            write_authorized=True, runner=runner,
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertEqual(len(runner.calls), 1)

    def test_nested_business_failure_with_id_is_unknown_and_not_retried(self):
        response = {
            "success": True,
            "data": {
                "success": False,
                "code": 500,
                "id": 12345,
                "message": "creation failed",
            },
        }
        runner = QueueRunner(completed(response))
        with self.assertRaises(ace_cli.AceCliError) as caught:
            ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=True, runner=runner,
            )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_REJECTED")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1, "nested failure must never trigger a retry")

    def test_array_nested_success_receipt_is_accepted(self):
        response = {
            "success": True,
            "id": 12345,
            "data": [{"success": True, "code": 0}],
        }
        runner = QueueRunner(completed(response))
        result = ace_cli.import_mind_map(
            MARKDOWN, TARGET, preflight=self.preflight,
            write_authorized=True, runner=runner,
        )
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["mind_map_id"], 12345)
        self.assertEqual(len(runner.calls), 1)

    def test_array_nested_business_failure_with_id_is_unknown_and_not_retried(self):
        response = {
            "success": True,
            "id": 12345,
            "data": [{"success": False, "code": 500}],
        }
        runner = QueueRunner(completed(response))
        with self.assertRaises(ace_cli.AceCliError) as caught:
            ace_cli.import_mind_map(
                MARKDOWN, TARGET, preflight=self.preflight,
                write_authorized=True, runner=runner,
            )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_REJECTED")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1, "array failure must never trigger a retry")

    def test_nested_nonzero_code_or_failure_status_overrides_outer_success(self):
        responses = [
            {"success": True, "data": {"success": True, "code": 500, "id": 12345}},
            {"success": True, "data": {"status": "FAILED", "id": 12345}},
        ]
        for response in responses:
            with self.subTest(response=response):
                runner = QueueRunner(completed(response))
                with self.assertRaises(ace_cli.AceCliError) as caught:
                    ace_cli.import_mind_map(
                        MARKDOWN, TARGET, preflight=self.preflight,
                        write_authorized=True, runner=runner,
                    )
                self.assertEqual(caught.exception.code, "ACE_IMPORT_REJECTED")
                self.assertTrue(caught.exception.unknown_outcome)
                self.assertEqual(len(runner.calls), 1)
    def test_cli_timeout_after_import_is_unknown_and_never_retried(self):
        runner = QueueRunner(subprocess.TimeoutExpired("zero-hub-cli", 180))
        with verified_mapping_builder():
            with self.assertRaises(ace_cli.AceCliError) as caught:
                ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1)

    def test_import_response_without_id_is_unknown_and_never_retried(self):
        runner = QueueRunner(completed({"success": True, "message": "created"}))
        with verified_mapping_builder():
            with self.assertRaises(ace_cli.AceCliError) as caught:
                ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1)

    def test_receipt_without_success_and_without_unique_id_stays_unknown(self):
        runner = QueueRunner(completed({
            "name": "created",
            "url": "https://testcase.example/CaseMindMapEdit",
        }))
        with verified_mapping_builder():
            with self.assertRaises(ace_cli.AceCliError) as caught:
                ace_cli.import_mind_map(
                    MARKDOWN, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(caught.exception.code, "ACE_IMPORT_SUCCESS_NOT_CONFIRMED")
        self.assertTrue(caught.exception.unknown_outcome)
        self.assertEqual(len(runner.calls), 1)

    def test_readback_missing_association_fields_is_not_proven(self):
        preview = platform_payloads.build_ace_preview(MARKDOWN, TARGET)
        readback = {
            "id": 12345,
            "name": preview["request"]["title"],
            "product_id": str(TARGET["product_id"]),
            "content": {"root": copy.deepcopy(preview["request"]["data"])},
        }
        result = ace_cli.verify_mind_map_readback(preview, readback, {"id": 12345}, 12345)
        self.assertEqual(result["content_status"], "PASS")
        self.assertEqual(result["association_status"], "NOT_PROVEN")
        self.assertIn("dir_id", result["association_missing_fields"])
        self.assertEqual(result["status"], "NOT_PROVEN")

    def test_conflicting_import_association_is_not_hidden_by_readback(self):
        preview = platform_payloads.build_ace_preview(MARKDOWN, TARGET)
        readback = make_readback(preview)
        import_result = dict(readback, dir_id=999)
        result = ace_cli.verify_mind_map_readback(preview, readback, import_result, 12345)
        self.assertEqual(result["association_status"], "NEED_FIX")
        self.assertIn("DIR_ID_MISMATCH", result["association_errors"])
        self.assertEqual(result["status"], "NEED_FIX")

    def test_readback_content_mismatch_is_need_fix(self):
        preview = platform_payloads.build_ace_preview(MARKDOWN, TARGET)
        readback = make_readback(preview)
        readback["content"]["root"]["children"][0]["children"][0]["data"]["icon"] = ["priority_5"]
        result = ace_cli.verify_mind_map_readback(preview, readback, readback, 12345)
        self.assertEqual(result["status"], "NEED_FIX")
        self.assertTrue(any("ICON_MISMATCH" in item for item in result["content_errors"]))

    def test_readback_accepts_platform_html_paragraph_wrappers(self):
        preview = platform_payloads.build_ace_preview(MARKDOWN, TARGET)
        readback = make_readback(preview)

        def wrap(node):
            node["data"]["text"] = "<p>" + node["data"]["text"] + "</p>"
            for child in node["children"]:
                wrap(child)

        wrap(readback["content"]["root"])
        result = ace_cli.verify_mind_map_readback(preview, readback, readback, 12345)
        self.assertEqual(result["status"], "PASS")

    def test_plain_text_preserves_business_text_and_html_entities(self):
        self.assertEqual(
            ace_cli._plain_text("字段显示<未配置>，a < b"),
            "字段显示<未配置>，a < b",
        )
        self.assertEqual(
            ace_cli._plain_text("字段显示&lt;未配置&gt;，a &lt; b"),
            "字段显示<未配置>，a < b",
        )
        self.assertEqual(
            ace_cli._expected_text("字段显示&lt;未配置&gt;，a &lt; b"),
            "字段显示<未配置>，a < b",
        )
        self.assertEqual(
            ace_cli._plain_text("&lt;p&gt;未配置&lt;/p&gt;"),
            "<p>未配置</p>",
        )

        markdown = MARKDOWN.replace(
            "只展示客户A的数据", "字段显示<未配置>，且 a < b"
        )
        preview = platform_payloads.build_ace_preview(markdown, TARGET)
        readback = make_readback(preview)
        expected_node = (
            readback["content"]["root"]["children"][0]["children"][0]
            ["children"][2]["children"][0]
        )
        expected_node["data"]["text"] = "预期：字段显示&lt;未配置&gt;，且 a &lt; b"
        result = ace_cli.verify_mind_map_readback(preview, readback, readback, 12345)
        self.assertEqual(result["status"], "PASS")

    def test_readback_detects_removed_angle_bracket_business_text(self):
        markdown = MARKDOWN.replace(
            "只展示客户A的数据", "字段显示<未配置>，且 a < b"
        )
        preview = platform_payloads.build_ace_preview(markdown, TARGET)
        readback = make_readback(preview)
        expected_node = (
            readback["content"]["root"]["children"][0]["children"][0]
            ["children"][2]["children"][0]
        )
        expected_node["data"]["text"] = "预期：字段显示"
        result = ace_cli.verify_mind_map_readback(preview, readback, readback, 12345)
        self.assertEqual(result["status"], "NEED_FIX")
        self.assertTrue(any("TEXT_MISMATCH" in item for item in result["content_errors"]))

    def test_preflight_rejects_reused_manifest_after_markdown_changes(self):
        changed_markdown = MARKDOWN.replace(
            "只展示客户A的数据", "修改后的业务预期"
        )
        runner = QueueRunner()
        changed_preview = verified_preview(changed_markdown, TARGET)
        with verified_mapping_builder(changed_preview):
            with self.assertRaisesRegex(
                ace_cli.AceCliError, "ACE_PREFLIGHT_MARKDOWN_MISMATCH"
            ):
                ace_cli.import_mind_map(
                    changed_markdown, TARGET, preflight=self.preflight,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(runner.calls, [])

    def test_markdown_change_before_create_is_caught_by_final_recheck(self):
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        markdown_item = next(
            item for item in manifest["artifacts"]
            if item.get("category") == "testcases" and item.get("role") == "markdown"
        )
        requirement_root = (
            self.manifest_path.parent.parent.parent
            if self.manifest_path.parent.parent.name == "versions"
            else self.manifest_path.parent.parent
        )
        markdown_path = requirement_root / Path(*markdown_item["path"].split("/"))
        original_loader = ace_cli._load_manifest_preflight
        calls = {"count": 0}

        def change_before_final_check(preview, manifest_ref):
            calls["count"] += 1
            if calls["count"] == 2:
                markdown_path.write_text(
                    markdown_path.read_text(encoding="utf-8") + "\n# changed",
                    encoding="utf-8",
                )
            return original_loader(preview, manifest_ref)

        runner = QueueRunner()
        with verified_mapping_builder():
            with patch.object(
                ace_cli, "_load_manifest_preflight", side_effect=change_before_final_check
            ):
                with self.assertRaises(ace_cli.AceCliError):
                    ace_cli.import_mind_map(
                        MARKDOWN, TARGET, preflight=self.preflight,
                        write_authorized=True, runner=runner,
                    )
        self.assertEqual(calls["count"], 2)
        self.assertEqual(runner.calls, [])

    def test_preflight_rejects_wrong_target(self):
        changed_target = dict(TARGET, project_id="790")
        bad_target = copy.deepcopy(self.preflight)
        runner = QueueRunner()
        with verified_mapping_builder(verified_preview(MARKDOWN, changed_target)):
            with self.assertRaisesRegex(
                ace_cli.AceCliError, "ACE_PREFLIGHT_TARGET_MISMATCH"
            ):
                ace_cli.import_mind_map(
                    MARKDOWN, changed_target, preflight=bad_target,
                    write_authorized=True, runner=runner,
                )
        self.assertEqual(runner.calls, [])
if __name__ == "__main__":
    unittest.main()
