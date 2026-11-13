from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from verify_bug_archive import (  # noqa: E402
    ArchiveVerificationError,
    main,
    verify_lifecycle_archive,
    verify_submission_archive,
)


class BugArchiveVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.manifest_cli = self.project / "skills/testcase-design/tools/manifest.py"
        self.manifest_cli.parent.mkdir(parents=True)
        self.manifest_cli.write_text("# test placeholder\n", encoding="utf-8")

        self.requirement_root = self.project / "output/requirement"
        self.latest_version = "20261106-v1"
        self.old_version = "20261105-v3"
        self.bug_id = "900001"
        self.role = f"bug-submission-{self.bug_id}"

        self.receipt = (
            self.requirement_root
            / "analysis"
            / self.old_version
            / "bug-submissions"
            / f"BUG-{self.bug_id}.md"
        )
        self.receipt.parent.mkdir(parents=True)
        self.receipt.write_text("历史版本中创建的 Bug 回执\n", encoding="utf-8")
        self.sha = hashlib.sha256(self.receipt.read_bytes()).hexdigest()

        self.manifest = {
            "version_id": self.latest_version,
            "artifacts": [{
                "category": "test-impact-analysis",
                "role": self.role,
                "path": f"analysis/{self.old_version}/bug-submissions/BUG-{self.bug_id}.md",
                "source_version": self.old_version,
                "change": "added",
                "sha256": self.sha,
            }],
        }
        self.manifest_path = (
            self.requirement_root / "versions" / self.latest_version / "manifest.json"
        )
        self.manifest_path.parent.mkdir(parents=True)
        self._write_manifest()

    def tearDown(self):
        self.temp.cleanup()

    def _write_manifest(self):
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False),
            encoding="utf-8",
        )

    def _runner(self, argv, **kwargs):
        command = argv[3]
        if command == "inspect":
            stdout = json.dumps({
                "result": "MANIFEST_BASELINE_READY",
                "latest_version": self.latest_version,
                "manifest_path": str(self.manifest_path),
            })
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if command == "validate":
            stdout = json.dumps({"result": "MANIFEST_HISTORY_PASS"})
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        raise AssertionError(f"Unexpected Manifest command: {command}")

    def _verify_submission(self, runner=None):
        return verify_submission_archive(
            self.requirement_root,
            self.bug_id,
            project_root=self.project,
            runner=runner or self._runner,
        )

    def test_submission_accepts_carried_forward_role_from_older_version(self):
        result = self._verify_submission()
        self.assertEqual(result["result"], "BUG_SUBMISSION_ARCHIVE_PASS")
        self.assertEqual(result["latest_version"], self.latest_version)
        self.assertEqual(result["manifest_role"], self.role)
        self.assertEqual(result["receipt_path"], self.manifest["artifacts"][0]["path"])
        self.assertEqual(result["sha256"], self.sha)
        self.assertEqual(result["manifest_validation"], "MANIFEST_HISTORY_PASS")

    def test_submission_rejects_non_object_manifest_root(self):
        for value in ([], None, "text", 42):
            with self.subTest(root=value):
                self.manifest = value
                self._write_manifest()
                with self.assertRaisesRegex(ArchiveVerificationError, "根节点不是 JSON object"):
                    self._verify_submission()

    def test_invalid_manifest_root_returns_structured_cli_failure(self):
        self.manifest = []
        self._write_manifest()
        original = verify_submission_archive

        def call_with_test_project(root, bug_id):
            return original(root, bug_id, project_root=self.project, runner=self._runner)

        with patch("verify_bug_archive.verify_submission_archive", side_effect=call_with_test_project):
            with patch("sys.stdout", new_callable=io.StringIO) as output:
                code = main(["submission", str(self.requirement_root), self.bug_id])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "BUG_ARCHIVE_FAIL")
        self.assertEqual(result["action"], "submission")
        self.assertIn("根节点不是 JSON object", result["error"])

    def test_submission_converts_manifest_read_failure(self):
        original = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == self.manifest_path:
                raise PermissionError("manifest read denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_text", autospec=True, side_effect=read_text):
            with self.assertRaisesRegex(ArchiveVerificationError, "无法读取最新版本 Manifest"):
                self._verify_submission()

    def test_submission_converts_receipt_stat_failure(self):
        original = Path.stat

        def stat(path, *args, **kwargs):
            if path == self.receipt:
                raise PermissionError("receipt stat denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "stat", autospec=True, side_effect=stat):
            with self.assertRaisesRegex(ArchiveVerificationError, "Bug 回执文件读取失败"):
                self._verify_submission()

    def test_submission_converts_receipt_read_failure(self):
        original = Path.read_bytes

        def read_bytes(path, *args, **kwargs):
            if path == self.receipt:
                raise PermissionError("receipt read denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
            with self.assertRaisesRegex(ArchiveVerificationError, "Bug 回执文件读取失败"):
                self._verify_submission()

    def test_submission_requires_exactly_one_role(self):
        self.manifest["artifacts"] = []
        self._write_manifest()
        with self.assertRaisesRegex(ArchiveVerificationError, "实际数量=0"):
            self._verify_submission()

    def test_submission_rejects_duplicate_role(self):
        self.manifest["artifacts"].append(dict(self.manifest["artifacts"][0]))
        self._write_manifest()
        with self.assertRaisesRegex(ArchiveVerificationError, "实际数量=2"):
            self._verify_submission()

    def test_submission_rejects_sha_mismatch(self):
        self.manifest["artifacts"][0]["sha256"] = "0" * 64
        self._write_manifest()
        with self.assertRaisesRegex(ArchiveVerificationError, "SHA-256 不一致"):
            self._verify_submission()

    def test_submission_rejects_missing_receipt(self):
        self.receipt.unlink()
        with self.assertRaisesRegex(ArchiveVerificationError, "文件不存在"):
            self._verify_submission()

    def test_submission_rejects_unsafe_manifest_path(self):
        self.manifest["artifacts"][0]["path"] = "../outside/BUG-900001.md"
        self._write_manifest()
        with self.assertRaisesRegex(ArchiveVerificationError, "非安全相对路径"):
            self._verify_submission()

    def test_submission_requires_manifest_history_validation(self):
        def failing_runner(argv, **kwargs):
            if argv[3] == "inspect":
                return self._runner(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 1, '{"result":"FAIL"}', "invalid")

        with self.assertRaisesRegex(ArchiveVerificationError, "validate 退出码"):
            self._verify_submission(runner=failing_runner)

    def test_submission_rejects_invalid_bug_id(self):
        with self.assertRaisesRegex(ArchiveVerificationError, "非法 Bug ID"):
            verify_submission_archive(
                self.requirement_root,
                "../900001",
                project_root=self.project,
                runner=self._runner,
            )

    def _make_lifecycle_dir(self):
        bug_dir = (
            self.requirement_root
            / self.latest_version
            / "analysis/bug-lifecycle/BUG-900002"
        )
        bug_dir.mkdir(parents=True, exist_ok=True)
        (bug_dir / "impact-analysis.md").write_text("影响分析\n", encoding="utf-8")
        (bug_dir / "close-receipt.md").write_text("关闭回执\n", encoding="utf-8")
        return bug_dir

    def test_lifecycle_verifies_required_files_and_sha(self):
        bug_dir = self._make_lifecycle_dir()
        result = verify_lifecycle_archive(
            bug_dir,
            "900002",
            project_root=self.project,
            runner=self._runner,
        )
        self.assertEqual(result["result"], "BUG_LIFECYCLE_ARCHIVE_PASS")
        self.assertEqual(result["manifest_registration"], "NOT_REGISTERED_BY_DESIGN")
        self.assertEqual(
            {item["path"] for item in result["files"]},
            {"impact-analysis.md", "close-receipt.md"},
        )
        self.assertTrue(all(len(item["sha256"]) == 64 for item in result["files"]))

    def test_lifecycle_converts_file_stat_failure(self):
        bug_dir = self._make_lifecycle_dir()
        target = bug_dir / "close-receipt.md"
        original = Path.stat

        def stat(path, *args, **kwargs):
            if path == target:
                raise PermissionError("lifecycle stat denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "stat", autospec=True, side_effect=stat):
            with self.assertRaisesRegex(ArchiveVerificationError, "Bug Lifecycle 文件读取失败"):
                verify_lifecycle_archive(bug_dir, "900002", project_root=self.project)

    def test_lifecycle_converts_file_read_failure(self):
        bug_dir = self._make_lifecycle_dir()
        target = bug_dir / "close-receipt.md"
        original = Path.read_bytes

        def read_bytes(path, *args, **kwargs):
            if path == target:
                raise PermissionError("lifecycle read denied")
            return original(path, *args, **kwargs)

        with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
            with self.assertRaisesRegex(ArchiveVerificationError, "Bug Lifecycle 文件读取失败"):
                verify_lifecycle_archive(bug_dir, "900002", project_root=self.project)

    def test_lifecycle_failure_returns_structured_cli_failure(self):
        bug_dir = self._make_lifecycle_dir()
        target = bug_dir / "close-receipt.md"
        original_read = Path.read_bytes
        original_verify = verify_lifecycle_archive

        def read_bytes(path, *args, **kwargs):
            if path == target:
                raise PermissionError("lifecycle read denied")
            return original_read(path, *args, **kwargs)

        def call_with_test_project(directory, bug_id, **kwargs):
            return original_verify(directory, bug_id, project_root=self.project, **kwargs)

        with patch.object(Path, "read_bytes", autospec=True, side_effect=read_bytes):
            with patch("verify_bug_archive.verify_lifecycle_archive", side_effect=call_with_test_project):
                with patch("sys.stdout", new_callable=io.StringIO) as output:
                    code = main(["lifecycle", str(bug_dir), "900002"])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual(result["result"], "BUG_ARCHIVE_FAIL")
        self.assertEqual(result["action"], "lifecycle")
        self.assertIn("读取失败", result["error"])

    def test_lifecycle_requires_manual_file_when_flagged(self):
        bug_dir = self._make_lifecycle_dir()
        with self.assertRaisesRegex(ArchiveVerificationError, "manual-verification.md 缺失"):
            verify_lifecycle_archive(
                bug_dir,
                "900002",
                manual_verification_required=True,
                project_root=self.project,
                runner=self._runner,
            )

    def test_lifecycle_validates_manifest_without_requiring_role(self):
        bug_dir = self._make_lifecycle_dir()
        result = verify_lifecycle_archive(
            bug_dir,
            "900002",
            requirement_root=self.requirement_root,
            project_root=self.project,
            runner=self._runner,
        )
        self.assertEqual(result["manifest_validation"], "MANIFEST_HISTORY_PASS")
        self.assertEqual(result["manifest_registration"], "NOT_REGISTERED_BY_DESIGN")

    def test_lifecycle_rejects_missing_required_file(self):
        bug_dir = self._make_lifecycle_dir()
        (bug_dir / "close-receipt.md").unlink()
        with self.assertRaisesRegex(ArchiveVerificationError, "必需文件缺失"):
            verify_lifecycle_archive(
                bug_dir,
                "900002",
                project_root=self.project,
                runner=self._runner,
            )

    def test_lifecycle_rejects_mismatched_bug_directory(self):
        bug_dir = self._make_lifecycle_dir()
        with self.assertRaisesRegex(ArchiveVerificationError, "目录与 Bug ID 不一致"):
            verify_lifecycle_archive(
                bug_dir,
                "900003",
                project_root=self.project,
                runner=self._runner,
            )


if __name__ == "__main__":
    unittest.main()
