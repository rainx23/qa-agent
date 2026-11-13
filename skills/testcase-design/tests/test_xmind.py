"""Real ZIP readback and tampering tests; no persistent output artifacts."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(TOOLS))
import artifacts  # noqa: E402
import xmind  # noqa: E402
from test_artifacts import MD
def _modify_xmind(path, callback):
    with ZipFile(path, "r") as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    content = json.loads(files["content.json"])
    callback(content)
    files["content.json"] = json.dumps(content, ensure_ascii=False).encode("utf-8")
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)


def _root(content):
    return content[0]["rootTopic"]


def _groups(content):
    return _root(content)["children"]["attached"]


def _cases(content):
    return _groups(content)[0]["children"]["attached"]


class XMindReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "testcases.xmind"

    def generate(self, markdown=MD):
        result = xmind.export_xmind(markdown, self.path)
        self.assertEqual(result["result"], "XMIND_READBACK_PASS")
        return result

    def test_real_zip_and_parsed_content_with_two_groups(self):
        report = self.generate()
        self.assertEqual((report["group_count"], report["case_count"], report["step_count"]), (2, 2, 3))
        self.assertFalse(report["desktop_open_verified"])
        self.assertEqual(xmind.read_xmind(self.path), xmind._display_projection(artifacts.parse_markdown(MD)))
        with ZipFile(self.path) as z:
            self.assertEqual(set(z.namelist()), {"content.json", "metadata.json", "manifest.json"})
            payload = z.read("content.json").decode("utf-8")
            self.assertNotIn("QA-900661-", payload)
            self.assertNotIn("Revision", payload)
            self.assertNotIn("Oracle", payload)
            root = json.loads(payload)[0]["rootTopic"]
            self.assertEqual(root["title"], "900661｜示例需求")
            self.assertEqual(root["structure"], "org.xmind.ui.logic.right")
            self.assertEqual(root["children"]["attached"][0]["title"], "一、核心业务")

    def test_optional_and_multiple_expected_structure(self):
        self.generate()
        actual = xmind.read_xmind(self.path)
        first = actual["groups"][0]["cases"][0]
        second = actual["groups"][1]["cases"][0]
        self.assertEqual(first["precondition"], "存在符合条件的数据")
        self.assertIsNone(first["test_data"])
        self.assertEqual(second["test_data"], "选择无匹配记录的条件")
        self.assertIsNone(second["precondition"])
        self.assertEqual(len(first["steps"][0]["expected"]), 2)
        self.assertEqual(len(first["steps"][1]["expected"]), 1)
        with ZipFile(self.path) as z:
            case = json.loads(z.read("content.json"))[0]["rootTopic"]["children"]["attached"][0]["children"]["attached"][0]
            self.assertEqual(case["markers"], [{"markerId": "priority-2"}])
            nodes = case["children"]["attached"]
            self.assertEqual(nodes[0]["title"], "前置条件：存在符合条件的数据")
            self.assertTrue(nodes[1]["title"].startswith("1. "))
            self.assertEqual(len(nodes[1]["children"]["attached"]), 2)

    def test_all_priorities_and_long_unicode_round_trip(self):
        long_text = "重要业务🙂校验" * 1400
        groups = ["# 900661｜多场景🙂需求", "", "## 动态业务分组"]
        for priority in range(5):
            groups += [
                f"### 核验场景{priority}",
                f"<!-- qa_case_id: QA-900661-{priority:010x} -->",
                f"- **优先级**：P{priority}",
                f"- **测试数据**：{long_text}" if priority == 0 else "",
                f"1. **操作**：核验{long_text}" if priority == 0 else f"1. **操作**：核验场景{priority}",
                f"   - **预期**：{long_text}" if priority == 0 else f"   - **预期**：场景{priority}完成",
                "",
            ]
        markdown = "\n".join(groups)
        report = self.generate(markdown)
        self.assertEqual(report["case_count"], 5)
        loaded = xmind.read_xmind(self.path)
        self.assertEqual([c["priority"] for c in loaded["groups"][0]["cases"]],
                         ["P0", "P1", "P2", "P3", "P4"])
        self.assertEqual(loaded["groups"][0]["cases"][0]["test_data"], long_text)
        self.assertEqual(loaded["groups"][0]["cases"][0]["steps"][0]["action"], "核验" + long_text)
        self.assertEqual(loaded["groups"][0]["cases"][0]["steps"][0]["expected"], [long_text])

    def test_reject_silent_case_omission(self):
        self.generate()
        _modify_xmind(self.path, lambda data: data[0]["rootTopic"]["children"]["attached"].pop())
        with self.assertRaisesRegex(artifacts.ArtifactError, "不一致"):
            xmind.verify_xmind(artifacts.parse_markdown(MD), self.path)

    def test_reject_modified_expectation(self):
        self.generate()
        def edit(data):
            step = _cases(data)[0]["children"]["attached"][1]
            step["children"]["attached"][0]["title"] = "预期：错误结果"
        _modify_xmind(self.path, edit)
        with self.assertRaisesRegex(artifacts.ArtifactError, "不一致"):
            xmind.verify_xmind(artifacts.parse_markdown(MD), self.path)

    def test_reject_priority_missing_or_wrong(self):
        for mutation in ("missing", "wrong"):
            with self.subTest(mutation=mutation):
                if self.path.exists():
                    self.path.unlink()
                self.generate()
                def edit(data):
                    if mutation == "missing":
                        _cases(data)[0].pop("markers")
                    else:
                        _cases(data)[0]["markers"] = [{"markerId": "priority-5"}]
                _modify_xmind(self.path, edit)
                with self.assertRaises(artifacts.ArtifactError):
                    xmind.verify_xmind(artifacts.parse_markdown(MD), self.path)

    def test_reject_reordered_groups_or_expected(self):
        for mutation in ("groups", "expected"):
            with self.subTest(mutation=mutation):
                if self.path.exists():
                    self.path.unlink()
                self.generate()
                def edit(data):
                    if mutation == "groups":
                        _groups(data).reverse()
                    else:
                        _cases(data)[0]["children"]["attached"][1]["children"]["attached"].reverse()
                _modify_xmind(self.path, edit)
                with self.assertRaisesRegex(artifacts.ArtifactError, "不一致"):
                    xmind.verify_xmind(artifacts.parse_markdown(MD), self.path)

    def test_reject_extra_unchecked_nodes_and_duplicate_topic_ids(self):
        for mutation in ("detached", "duplicate", "nested_leaf", "additional_key"):
            with self.subTest(mutation=mutation):
                if self.path.exists():
                    self.path.unlink()
                self.generate()
                def edit(data):
                    if mutation == "detached":
                        _root(data)["children"]["detached"] = [{"title": "不可静默丢失"}]
                    elif mutation == "duplicate":
                        _cases(data)[0]["id"] = _groups(data)[0]["id"]
                    elif mutation == "nested_leaf":
                        exp = _cases(data)[0]["children"]["attached"][1]["children"]["attached"][0]
                        exp["children"] = {"attached": [{"id": "alien", "class": "topic", "title": "多余内容"}]}
                    elif mutation == "additional_key":
                        _cases(data)[0]["notes"] = {"plain": {"content": "隐藏内容"}}
                _modify_xmind(self.path, edit)
                with self.assertRaises(artifacts.ArtifactError):
                    xmind.verify_xmind(artifacts.parse_markdown(MD), self.path)

    def test_reject_unexpected_technical_identity_in_display(self):
        self.generate()
        _modify_xmind(self.path, lambda data: _cases(data)[0].update(
            title="QA-900661-0123456789 页面筛选后显示符合条件的结果"))
        with self.assertRaisesRegex(artifacts.ArtifactError, "内部 Case ID"):
            xmind.read_xmind(self.path)

    def test_corrupt_file_and_wrong_extension(self):
        with self.assertRaisesRegex(artifacts.ArtifactError, "必须以 .xmind"):
            xmind.export_xmind(MD, self.root / "wrong.json")
        self.path.write_bytes(b"not a zip")
        with self.assertRaises(artifacts.ArtifactError):
            xmind.read_xmind(self.path)

    def test_existing_xmind_never_overwritten(self):
        self.generate()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(artifacts.ArtifactError, "不覆盖"):
            xmind.export_xmind(MD, self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_markdown_does_not_write(self):
        with self.assertRaises(artifacts.ArtifactError):
            xmind.export_xmind(MD.replace("QA-900661-abcdef1234", "QA-900661-0123456789"), self.path)
        self.assertFalse(self.path.exists())

    def test_corrupted_deflate_stream_returns_json_fail_without_traceback(self):
        """Damage compressed member bytes without deleting the ZIP central directory."""
        import os
        import subprocess

        self.generate()
        with ZipFile(self.path, "r") as archive:
            entry = archive.getinfo("content.json")
        raw = bytearray(self.path.read_bytes())
        header = entry.header_offset
        self.assertEqual(raw[header:header + 4], b"PK\x03\x04")
        filename_size = int.from_bytes(raw[header + 26:header + 28], "little")
        extra_size = int.from_bytes(raw[header + 28:header + 30], "little")
        compressed_offset = header + 30 + filename_size + extra_size
        raw[compressed_offset] = 0xff  # Invalid DEFLATE block type.
        self.path.write_bytes(raw)

        with self.assertRaisesRegex(artifacts.ArtifactError, "损坏"):
            xmind.read_xmind(self.path)

        markdown_file = self.root / "testcases.md"
        markdown_file.write_text(MD, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "gbk:strict"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", str(TOOLS / "xmind.py"),
             str(markdown_file), str(self.path), "--verify"],
            capture_output=True, env=env, timeout=15,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        output = json.loads(result.stdout.decode("gbk"))
        self.assertEqual(output["result"], "FAIL")
        self.assertIn("损坏", output["error"])

    def test_partial_write_failure_cleans_only_created_file_then_retry_succeeds(self):
        native_open = Path.open

        class BrokenWriter:
            def __init__(self, underlying):
                self.underlying = underlying

            def __enter__(self):
                self.underlying.__enter__()
                return self

            def write(self, payload):
                self.underlying.write(payload[:40])
                raise OSError("模拟磁盘写入失败🙂")

            def __exit__(self, *args):
                return self.underlying.__exit__(*args)

        def failing_open(file_path, mode="r", *args, **kwargs):
            underlying = native_open(file_path, mode, *args, **kwargs)
            return BrokenWriter(underlying) if file_path == self.path and mode == "xb" else underlying

        md = self.root / "testcases.md"
        md.write_text(MD, encoding="utf-8")
        output = io.StringIO()
        with patch.object(Path, "open", failing_open), patch.object(sys, "stdout", output):
            status = xmind.main([str(md), str(self.path)])
        self.assertEqual(status, 1)
        failed = json.loads(output.getvalue())
        self.assertEqual(failed["result"], "FAIL")
        self.assertIn("模拟磁盘写入失败🙂", failed["error"])
        self.assertFalse(self.path.exists(), "写入 40 字节后抛异常不能留下残留")
        self.assertEqual(xmind.export_xmind(MD, self.path)["result"], "XMIND_READBACK_PASS")

        # A pre-existing archive is NOT part of the current attempted write.
        original = self.path.read_bytes()
        with patch.object(Path, "open", failing_open):
            with self.assertRaisesRegex(artifacts.ArtifactError, "不覆盖"):
                xmind.export_xmind(MD, self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_readback_failure_cleans_new_file_not_existing(self):
        with patch.object(xmind, "verify_xmind", side_effect=artifacts.ArtifactError("注入回读失败")):
            with self.assertRaisesRegex(artifacts.ArtifactError, "注入回读失败"):
                xmind.export_xmind(MD, self.path)
        self.assertFalse(self.path.exists())
        self.assertEqual(xmind.export_xmind(MD, self.path)["result"], "XMIND_READBACK_PASS")

    def test_cli_generate_verify_and_gbk_failure(self):
        md = self.root / "testcases.md"
        md.write_text(MD, encoding="utf-8")
        buf = io.BytesIO()
        target = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
        with patch.object(sys, "stdout", target):
            code = xmind.main([str(md), str(self.path)])
            target.flush()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buf.getvalue().decode("gbk"))["result"], "XMIND_READBACK_PASS")
        self.assertEqual(xmind.main([str(md), str(self.path), "--verify"]), 0)
        changed = MD.replace("### 无匹配数据时提示空结果", "### 不符合的标题🙂")
        md.write_text(changed, encoding="utf-8")
        buf = io.BytesIO()
        target = io.TextIOWrapper(buf, encoding="gbk", errors="strict")
        with patch.object(sys, "stdout", target):
            code = xmind.main([str(md), str(self.path), "--verify"])
            target.flush()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(buf.getvalue().decode("gbk"))["result"], "FAIL")


if __name__ == "__main__":
    unittest.main()
