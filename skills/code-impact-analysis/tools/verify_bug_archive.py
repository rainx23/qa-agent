#!/usr/bin/env python3
"""Read-only archive verification for the P2 Bug Submission and Lifecycle workflows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable, Any


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERSION_RE = re.compile(r"^\d{8}-v[1-9]\d*$")
BUG_ID_RE = re.compile(r"^\d+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ArchiveVerificationError(RuntimeError):
    """Raised when an archive cannot be proven complete and consistent."""


def _resolve_from_project(value: str | Path, project_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def _ensure_inside(path: Path, parent: Path, label: str) -> None:
    try:
        path.relative_to(parent)
    except ValueError as exc:
        raise ArchiveVerificationError(f"{label} 路径越出归档根目录：{path}") from exc


def _verified_file_info(path: Path, label: str, missing_message: str) -> tuple[int, str]:
    """Read one archive file, converting filesystem failures to a stable failure."""
    try:
        if not path.is_file():
            raise ArchiveVerificationError(f"{missing_message}：{path}")
        size = path.stat().st_size
        if size <= 0:
            raise ArchiveVerificationError(f"{label}为空：{path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ArchiveVerificationError(f"{label}读取失败：{path}：{exc}") from exc
    return size, digest


def _run_manifest_cli(
    project_root: Path,
    command: str,
    requirement_root: Path,
    runner: Callable[..., Any],
) -> dict[str, Any]:
    manifest_cli = project_root / "skills" / "testcase-design" / "tools" / "manifest.py"
    if not manifest_cli.is_file():
        raise ArchiveVerificationError(f"Manifest CLI 不存在：{manifest_cli}")

    argv = [
        sys.executable,
        "-B",
        str(manifest_cli),
        command,
        str(requirement_root),
    ]
    try:
        completed = runner(
            argv,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchiveVerificationError(f"Manifest CLI 执行失败：{exc}") from exc

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode != 0:
        detail = (stderr or stdout).strip()[-1500:]
        raise ArchiveVerificationError(
            f"manifest.py {command} 退出码 {completed.returncode}：{detail}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ArchiveVerificationError(
            f"manifest.py {command} 未返回有效 JSON：{stdout.strip()[-1500:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise ArchiveVerificationError(f"manifest.py {command} 返回结构不是 JSON object")
    return payload


def verify_submission_archive(
    requirement_root: str | Path,
    bug_id: str,
    *,
    project_root: str | Path = PROJECT_ROOT,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Verify the current Manifest's unique Bug Submission role, file SHA and history."""
    bug_id = str(bug_id)
    if not BUG_ID_RE.fullmatch(bug_id):
        raise ArchiveVerificationError(f"非法 Bug ID：{bug_id}")

    project = Path(project_root).resolve()
    root = _resolve_from_project(requirement_root, project)
    _ensure_inside(root, project, "需求归档根目录")
    if not root.is_dir():
        raise ArchiveVerificationError(f"需求归档根目录不存在：{root}")

    inspected = _run_manifest_cli(project, "inspect", root, runner)
    if inspected.get("result") != "MANIFEST_BASELINE_READY":
        raise ArchiveVerificationError(
            f"Manifest inspect 未就绪：{inspected.get('result', 'UNKNOWN')}"
        )

    latest_version = inspected.get("latest_version")
    if not isinstance(latest_version, str) or not VERSION_RE.fullmatch(latest_version):
        raise ArchiveVerificationError(f"inspect 返回的 latest_version 无效：{latest_version!r}")

    manifest_value = inspected.get("manifest_path")
    manifest_path = (
        Path(manifest_value)
        if isinstance(manifest_value, str) and manifest_value
        else root / "versions" / latest_version / "manifest.json"
    )
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest_path = manifest_path.resolve()
    _ensure_inside(manifest_path, root, "Manifest")
    try:
        if not manifest_path.is_file():
            raise ArchiveVerificationError(f"最新版本 Manifest 不存在：{manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveVerificationError(f"无法读取最新版本 Manifest：{exc}") from exc
    if not isinstance(manifest, dict):
        raise ArchiveVerificationError("最新版本 Manifest 根节点不是 JSON object")

    if manifest.get("version_id") != latest_version:
        raise ArchiveVerificationError(
            f"Manifest 版本不一致：inspect={latest_version}，file={manifest.get('version_id')!r}"
        )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ArchiveVerificationError("最新 Manifest 的 artifacts 不是数组")

    role = f"bug-submission-{bug_id}"
    matches = [
        item for item in artifacts
        if isinstance(item, dict) and item.get("role") == role
    ]
    if len(matches) != 1:
        raise ArchiveVerificationError(
            f"最新 Manifest 中 role={role} 应唯一存在，实际数量={len(matches)}"
        )

    item = matches[0]
    if item.get("category") != "test-impact-analysis":
        raise ArchiveVerificationError(
            f"{role} category 错误：{item.get('category')!r}"
        )

    relative_path = Path(str(item.get("path") or ""))
    if relative_path.is_absolute() or any(part in ("", ".", "..") for part in relative_path.parts):
        raise ArchiveVerificationError(f"{role} 的 artifact path 非安全相对路径")
    expected_tail = ("bug-submissions", f"BUG-{bug_id}.md")
    path_parts = relative_path.parts
    source_version = item.get("source_version")
    new_layout = (
        len(path_parts) >= 4
        and path_parts[0] in {"analysis", "test-impact-analysis"}
        and path_parts[1] == source_version
        and tuple(path_parts[-2:]) == expected_tail
    )
    legacy_layout = (
        len(path_parts) >= 4
        and path_parts[0] == source_version
        and path_parts[1] in {"analysis", "test-impact-analysis"}
        and tuple(path_parts[-2:]) == expected_tail
    )
    if not (new_layout or legacy_layout):
        raise ArchiveVerificationError(
            f"{role} 的 artifact path 不符合归档约定：{relative_path.as_posix()}"
        )

    receipt_path = (root / relative_path).resolve()
    _ensure_inside(receipt_path, root, "Bug 回执")
    _, actual_sha = _verified_file_info(
        receipt_path, "Bug 回执文件", "Manifest 登记的 Bug 回执文件不存在"
    )

    expected_sha = item.get("sha256")
    if not isinstance(expected_sha, str) or not SHA256_RE.fullmatch(expected_sha):
        raise ArchiveVerificationError(f"{role} 的 Manifest SHA-256 格式无效")
    if actual_sha != expected_sha:
        raise ArchiveVerificationError(
            f"{role} SHA-256 不一致：Manifest={expected_sha}，实际={actual_sha}"
        )

    validated = _run_manifest_cli(project, "validate", root, runner)
    if validated.get("result") != "MANIFEST_HISTORY_PASS":
        raise ArchiveVerificationError(
            f"Manifest validate 未通过：{validated.get('result', 'UNKNOWN')}"
        )

    return {
        "result": "BUG_SUBMISSION_ARCHIVE_PASS",
        "bug_id": bug_id,
        "latest_version": latest_version,
        "manifest_role": role,
        "category": item["category"],
        "receipt_path": relative_path.as_posix(),
        "sha256": actual_sha,
        "manifest_validation": validated["result"],
    }


def verify_lifecycle_archive(
    bug_directory: str | Path,
    bug_id: str,
    *,
    manual_verification_required: bool = False,
    requirement_root: str | Path | None = None,
    project_root: str | Path = PROJECT_ROOT,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Verify Bug Lifecycle files; do not require a Manifest role unsupported by the schema."""
    bug_id = str(bug_id)
    if not BUG_ID_RE.fullmatch(bug_id):
        raise ArchiveVerificationError(f"非法 Bug ID：{bug_id}")

    project = Path(project_root).resolve()
    bug_dir = _resolve_from_project(bug_directory, project)
    _ensure_inside(bug_dir, project, "Bug Lifecycle 目录")
    if not bug_dir.is_dir():
        raise ArchiveVerificationError(f"Bug Lifecycle 目录不存在：{bug_dir}")
    if bug_dir.name != f"BUG-{bug_id}":
        raise ArchiveVerificationError(
            f"Bug Lifecycle 目录与 Bug ID 不一致：目录={bug_dir.name}，ID={bug_id}"
        )

    expected_names = ["impact-analysis.md", "close-receipt.md"]
    manual_path = bug_dir / "manual-verification.md"
    try:
        if manual_verification_required and not manual_path.is_file():
            raise ArchiveVerificationError("存在必须归档的人工核对项，但 manual-verification.md 缺失")
        if manual_path.exists():
            expected_names.append("manual-verification.md")
    except OSError as exc:
        raise ArchiveVerificationError(f"人工核对归档文件访问失败：{exc}") from exc

    files: list[dict[str, str | int]] = []
    for name in expected_names:
        path = (bug_dir / name).resolve()
        _ensure_inside(path, bug_dir.resolve(), name)
        size, actual_sha = _verified_file_info(
            path, "Bug Lifecycle 文件", "Bug Lifecycle 必需文件缺失"
        )
        files.append({
            "path": path.relative_to(bug_dir).as_posix(),
            "bytes": size,
            "sha256": actual_sha,
        })

    manifest_validation = "NOT_RUN_NO_REQUIREMENT_ROOT"
    if requirement_root is not None:
        root = _resolve_from_project(requirement_root, project)
        _ensure_inside(root, project, "需求归档根目录")
        validated = _run_manifest_cli(project, "validate", root, runner)
        if validated.get("result") != "MANIFEST_HISTORY_PASS":
            raise ArchiveVerificationError(
                f"需求 Manifest validate 未通过：{validated.get('result', 'UNKNOWN')}"
            )
        manifest_validation = validated["result"]

    return {
        "result": "BUG_LIFECYCLE_ARCHIVE_PASS",
        "bug_id": bug_id,
        "bug_directory": bug_dir.relative_to(project).as_posix(),
        "files": files,
        "manifest_validation": manifest_validation,
        "manifest_registration": "NOT_REGISTERED_BY_DESIGN",
    }


def main(argv: list[str] | None = None) -> int:
    _configure_console_encoding()
    parser = argparse.ArgumentParser(
        description="只读核验 Bug Submission / Bug Lifecycle 本地归档。"
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    submission = subparsers.add_parser("submission", help="核验创建回执与最新 Manifest")
    submission.add_argument("requirement_root")
    submission.add_argument("bug_id")

    lifecycle = subparsers.add_parser("lifecycle", help="核验 Bug Lifecycle 文件")
    lifecycle.add_argument("bug_directory")
    lifecycle.add_argument("bug_id")
    lifecycle.add_argument("--manual-verification", action="store_true")
    lifecycle.add_argument("--requirement-root")

    args = parser.parse_args(argv)
    try:
        if args.action == "submission":
            result = verify_submission_archive(args.requirement_root, args.bug_id)
        else:
            result = verify_lifecycle_archive(
                args.bug_directory,
                args.bug_id,
                manual_verification_required=args.manual_verification,
                requirement_root=args.requirement_root,
            )
    except ArchiveVerificationError as exc:
        print(json.dumps(
            {"result": "BUG_ARCHIVE_FAIL", "action": args.action, "error": str(exc)},
            ensure_ascii=False,
            sort_keys=True,
        ))
        return 1

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
