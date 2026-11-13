"""Self-contained Zero Hub CLI adapter for ACE TestCase.

The adapter consumes canonical testcase Markdown through platform_payloads.
It does not depend on another Skill's files and never falls back to MCP writes.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, urlparse

try:
    import manifest as manifest_tools
    import platform_payloads
except ImportError:  # pragma: no cover - package-style import
    from . import manifest as manifest_tools, platform_payloads


Runner = Callable[..., Any]
TARGET_FIELDS = (
    "product_id", "dir_id", "project_id", "project_name", "story_id", "story_name"
)
ID_KEYS = {
    "id", "case_id", "caseId", "mind_map_id", "mindMapId", "mindmap_id",
    "mindmapId", "collection_id", "created_id",
}
NESTED_RESULT_KEYS = (
    "data", "result", "mind_map", "mindMap", "mindmap", "collection", "metadata"
)
FIELD_ALIASES = {
    "product_id": ("product_id", "productId"),
    "dir_id": ("dir_id", "dirId", "directory_id", "directoryId"),
    "project_id": ("project_id", "projectId"),
    "project_name": ("project_name", "projectName"),
    "story_id": ("story_id", "storyId"),
    "story_name": ("story_name", "storyName"),
}


class AceCliError(RuntimeError):
    """A bounded ACE CLI failure with an explicit write-outcome classification."""

    def __init__(
        self,
        code: str,
        *,
        unknown_outcome: bool = False,
        detail: str = "",
        status: str | None = None,
        mind_map_id: int | None = None,
    ):
        self.code = code
        self.unknown_outcome = unknown_outcome
        self.detail = detail
        self.status = status
        self.mind_map_id = mind_map_id
        super().__init__(code if not detail else code + ": " + detail)


def _positive_id(value: object, field: str) -> str:
    if isinstance(value, bool):
        raise AceCliError("ACE_" + field + "_INVALID")
    text = str(value).strip()
    if not re.fullmatch(r"\d+", text) or int(text) <= 0:
        raise AceCliError("ACE_" + field + "_INVALID")
    return str(int(text))


def _normalise_target(target: object) -> dict:
    if not isinstance(target, dict):
        raise AceCliError("ACE_TARGET_INVALID")
    result = dict(target)
    result["product_id"] = int(_positive_id(result.get("product_id"), "PRODUCT_ID"))
    result["dir_id"] = int(_positive_id(result.get("dir_id"), "DIR_ID"))
    result["project_id"] = _positive_id(result.get("project_id"), "PROJECT_ID")
    result["story_id"] = _positive_id(result.get("story_id"), "STORY_ID")
    return result


def resolve_cli(executable: str | Path | None = None) -> str:
    """Resolve the CLI from PATH or an explicit/environment override."""
    candidate = str(executable or os.environ.get("ZERO_HUB_CLI") or "zero-hub-cli").strip()
    candidate_path = Path(candidate).expanduser()
    if candidate_path.is_file():
        return str(candidate_path.resolve())
    resolved = shutil.which(candidate)
    if resolved:
        return resolved
    raise AceCliError("ACE_CLI_NOT_FOUND", detail="未发现 zero-hub-cli；请检查当前执行环境")


def _run_json(
    args: Sequence[str],
    *,
    executable: str | Path | None = None,
    timeout_seconds: int = 120,
    runner: Runner = subprocess.run,
    write_operation: bool = False,
) -> Any:
    argv = [resolve_cli(executable), "ace-testcase", *[str(item) for item in args], "--json"]
    try:
        result = runner(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise AceCliError(
            "ACE_CLI_TIMEOUT",
            unknown_outcome=write_operation,
            detail="命令超时；不得重新发起写入",
        ) from exc
    except OSError as exc:
        raise AceCliError(
            "ACE_CLI_EXECUTION_FAILED",
            unknown_outcome=write_operation,
            detail=type(exc).__name__,
        ) from exc

    if result.returncode != 0:
        detail = (getattr(result, "stderr", "") or "").strip()
        raise AceCliError(
            "ACE_CLI_NONZERO_EXIT",
            unknown_outcome=write_operation,
            detail=detail[:240],
        )
    stdout = getattr(result, "stdout", "") or ""
    try:
        return json.loads(stdout.lstrip("\ufeff"))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AceCliError(
            "ACE_CLI_INVALID_JSON",
            unknown_outcome=write_operation,
            detail="CLI 未返回可解析的 JSON",
        ) from exc


def list_projects(
    *, executable: str | Path | None = None, runner: Runner = subprocess.run
) -> list[dict]:
    result = _run_json(["list-projects"], executable=executable, runner=runner)
    if not isinstance(result, list):
        raise AceCliError("ACE_PROJECT_LIST_INVALID")
    for item in result:
        if not isinstance(item, dict) or not item.get("name"):
            raise AceCliError("ACE_PROJECT_LIST_ITEM_INVALID")
        _positive_id(item.get("id"), "PROJECT_LIST_ID")
    return result


def get_project_directories(
    project_id: object,
    *,
    executable: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> list[dict]:
    project = _positive_id(project_id, "PROJECT_ID")
    result = _run_json(
        ["project-dir", "--project-id", project],
        executable=executable,
        runner=runner,
    )
    if not isinstance(result, list) or not all(isinstance(item, dict) for item in result):
        raise AceCliError("ACE_DIRECTORY_TREE_INVALID")
    return result


def flatten_directory_tree(roots: list[dict]) -> list[dict]:
    """Return directory records with complete paths and observed mind_count."""
    if not isinstance(roots, list):
        raise AceCliError("ACE_DIRECTORY_TREE_INVALID")
    flattened: list[dict] = []

    def visit(node: dict, parent_path: tuple[str, ...]) -> None:
        if not isinstance(node, dict):
            raise AceCliError("ACE_DIRECTORY_NODE_INVALID")
        name = str(node.get("name") or "").strip()
        if not name:
            raise AceCliError("ACE_DIRECTORY_NAME_MISSING")
        path_parts = parent_path + (name,)
        children = node.get("children") or []
        if not isinstance(children, list):
            raise AceCliError("ACE_DIRECTORY_CHILDREN_INVALID")
        # The CLI returns the project root as a virtual node (isRoot=true, id=null).
        # Keep its name in the complete path, but do not expose it as a selectable directory.
        if node.get("isRoot") is True and node.get("id") is None:
            for child in children:
                visit(child, path_parts)
            return
        directory_id = _positive_id(node.get("id"), "DIR_ID")
        flattened.append({
            "id": int(directory_id),
            "name": name,
            "path": "/".join(path_parts),
            "parent_id": node.get("parent_id"),
            "project_id": node.get("project_id"),
            "mind_count": node.get("mind_count"),
            "child_count": len(children),
        })
        for child in children:
            visit(child, path_parts)

    for root in roots:
        visit(root, ())
    return flattened


def find_directory_by_path(roots: list[dict], full_path: str) -> dict:
    """Resolve only an exact complete directory path; never guess a leaf name."""
    requested = "/".join(
        part.strip() for part in re.split(r"[/\\]+", str(full_path)) if part.strip()
    )
    if not requested:
        raise AceCliError("ACE_DIRECTORY_PATH_EMPTY")
    matches = [item for item in flatten_directory_tree(roots) if item["path"] == requested]
    if not matches:
        raise AceCliError("ACE_DIRECTORY_PATH_NOT_FOUND", detail=requested)
    if len(matches) != 1:
        raise AceCliError("ACE_DIRECTORY_PATH_AMBIGUOUS", detail=requested)
    return matches[0]


def _readback_root(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise AceCliError("ACE_READBACK_INVALID")
    content = payload.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AceCliError("ACE_READBACK_CONTENT_INVALID") from exc
    root = content.get("root") if isinstance(content, dict) else None
    if not isinstance(root, dict):
        raise AceCliError("ACE_READBACK_ROOT_MISSING")
    return root


def get_mind_map(
    case_id: object,
    *,
    executable: str | Path | None = None,
    runner: Runner = subprocess.run,
) -> dict:
    mind_map_id = _positive_id(case_id, "MIND_MAP_ID")
    result = _run_json(
        ["get-mind-map", "--case-id", mind_map_id],
        executable=executable,
        runner=runner,
    )
    _readback_root(result)
    return result


def _result_containers(value: object):
    """Walk nested business-result dictionaries and arrays from JSON receipts."""
    if isinstance(value, dict):
        yield value
        for key in NESTED_RESULT_KEYS:
            child = value.get(key)
            if isinstance(child, (dict, list)):
                yield from _result_containers(child)
    elif isinstance(value, list):
        for child in value:
            if isinstance(child, (dict, list)):
                yield from _result_containers(child)


def _validate_import_receipt(result: object) -> bool:
    """Reject explicit failures and report whether the receipt has an explicit success signal.

    Some ACE MCP versions document only id/name/url in the create response. A unique
    ID without a success flag is not success by itself; it only authorizes a readback
    attempt by that ID.
    """
    if not isinstance(result, dict):
        raise AceCliError(
            "ACE_IMPORT_RECEIPT_INVALID",
            unknown_outcome=True,
            detail="创建回执不是 JSON 对象；禁止重试",
        )

    success_confirmed = False
    failure_statuses = {"FAIL", "FAILED", "ERROR", "FAILURE", "REJECTED"}
    success_statuses = {"SUCCESS", "SUCCEEDED", "CREATED", "OK"}
    false_values = {"FALSE", "0", "NO", "FAIL", "FAILED", "ERROR"}
    true_values = {"TRUE", "1", "YES", "SUCCESS", "SUCCEEDED"}

    for container in _result_containers(result):
        if "success" in container and container["success"] is not None:
            value = container["success"]
            if isinstance(value, bool):
                if value:
                    success_confirmed = True
                else:
                    raise AceCliError(
                        "ACE_IMPORT_REJECTED",
                        unknown_outcome=True,
                        detail="创建回执的嵌套业务结果明确返回 success=false；禁止重试",
                    )
            elif isinstance(value, (int, float)):
                if value == 0:
                    raise AceCliError(
                        "ACE_IMPORT_REJECTED",
                        unknown_outcome=True,
                        detail="创建回执的嵌套业务结果明确返回 success=0；禁止重试",
                    )
                if value == 1:
                    success_confirmed = True
            elif isinstance(value, str):
                normalized = value.strip().upper()
                if normalized in false_values:
                    raise AceCliError(
                        "ACE_IMPORT_REJECTED",
                        unknown_outcome=True,
                        detail="创建回执的嵌套业务结果明确返回失败；禁止重试",
                    )
                if normalized in true_values:
                    success_confirmed = True

        receipt_status = str(container.get("status") or "").strip().upper()
        if receipt_status in failure_statuses:
            raise AceCliError(
                "ACE_IMPORT_REJECTED",
                unknown_outcome=True,
                detail="创建回执的嵌套业务状态为 " + receipt_status + "；禁止重试",
            )
        if receipt_status in success_statuses:
            success_confirmed = True

        if "code" in container and container["code"] is not None:
            code = str(container["code"]).strip()
            if code != "0":
                raise AceCliError(
                    "ACE_IMPORT_REJECTED",
                    unknown_outcome=True,
                    detail="创建回执的嵌套业务 code=" + code + "；禁止重试",
                )
            success_confirmed = True

    if not success_confirmed:
        try:
            extract_created_mind_map_id(result)
        except AceCliError as exc:
            raise AceCliError(
                "ACE_IMPORT_SUCCESS_NOT_CONFIRMED",
                unknown_outcome=True,
                detail="创建回执缺少明确成功状态且未包含唯一 MindMap ID；禁止重试",
            ) from exc
    return success_confirmed


def extract_created_mind_map_id(result: object) -> int:
    """Extract one unambiguous MindMap ID from the import JSON response."""
    candidates: set[int] = set()
    for container in _result_containers(result):
        for key in ID_KEYS:
            value = container.get(key)
            if value is None or isinstance(value, (dict, list, bool)):
                continue
            text = str(value).strip()
            if re.fullmatch(r"\d+", text) and int(text) > 0:
                candidates.add(int(text))
        for key in ("url", "link"):
            value = container.get(key)
            if isinstance(value, str):
                query_id = parse_qs(urlparse(value).query).get("id", [])
                for item in query_id:
                    if item.isdigit() and int(item) > 0:
                        candidates.add(int(item))
    if len(candidates) != 1:
        raise AceCliError(
            "ACE_IMPORT_ID_UNRESOLVED",
            unknown_outcome=True,
            detail="创建响应未包含唯一可确认的 MindMap ID；禁止重试",
        )
    return next(iter(candidates))


def _plain_text(value: object) -> str:
    """Remove only confirmed ACE paragraph/line-break wrappers.

    Decode entities after wrapper handling so escaped business text becomes
    literal text rather than markup to be deleted. Unknown angle-bracket
    content is always preserved.
    """
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>\s*<p(?:\s[^>]*)?>", "\n", text)
    text = re.sub(r"(?i)^<p(?:\s[^>]*)?>", "", text)
    text = re.sub(r"(?i)</p>$", "", text)
    return html.unescape(text).strip()


def _expected_text(value: object) -> str:
    """Decode Markdown HTML entities without treating business text as markup."""
    return html.unescape(str(value or "")).strip()



def _node_tags(data: dict) -> list[str]:
    raw = data.get("tag") or []
    if not isinstance(raw, list):
        return []
    return [
        str(item.get("text") or "").strip()
        for item in raw
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]


def _node_icons(data: dict) -> list[str]:
    raw = data.get("icon") or []
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _compare_nodes(expected: dict, actual: dict, location: str, errors: list[str]) -> None:
    expected_data = expected.get("data") if isinstance(expected.get("data"), dict) else {}
    actual_data = actual.get("data") if isinstance(actual.get("data"), dict) else {}
    expected_text = _expected_text(expected_data.get("text"))
    actual_text = _plain_text(actual_data.get("text"))
    if expected_text != actual_text:
        errors.append(location + ":TEXT_MISMATCH")
    if _node_tags(expected_data) != _node_tags(actual_data):
        errors.append(location + ":TAG_MISMATCH")
    if _node_icons(expected_data) != _node_icons(actual_data):
        errors.append(location + ":ICON_MISMATCH")
    expected_uid = str(expected_data.get("uid") or "")
    actual_uid = str(actual_data.get("uid") or "")
    if expected_uid and expected_uid != actual_uid:
        errors.append(location + ":UID_MISMATCH")

    expected_children = expected.get("children") or []
    actual_children = actual.get("children") or []
    if not isinstance(expected_children, list) or not isinstance(actual_children, list):
        errors.append(location + ":CHILDREN_INVALID")
        return
    if len(expected_children) != len(actual_children):
        errors.append(location + ":CHILD_COUNT_MISMATCH")
    for index, (expected_child, actual_child) in enumerate(
        zip(expected_children, actual_children), 1
    ):
        if not isinstance(expected_child, dict) or not isinstance(actual_child, dict):
            errors.append(location + f"/{index}:NODE_INVALID")
            continue
        _compare_nodes(expected_child, actual_child, location + f"/{index}", errors)


def _normalise_identifier(value: object) -> str:
    text = str(value).strip()
    return str(int(text)) if re.fullmatch(r"\d+", text) else text


def _lookup_metadata_values(payloads: list[object], field: str) -> list[object]:
    """Collect every available copy so a conflicting receipt cannot be hidden."""
    aliases = FIELD_ALIASES[field]
    values: list[object] = []
    for payload in payloads:
        for container in _result_containers(payload):
            for alias in aliases:
                if alias in container and container[alias] is not None:
                    values.append(container[alias])
    return values


def _count_nodes(node: object) -> int:
    if not isinstance(node, dict):
        return 0
    children = node.get("children") or []
    if not isinstance(children, list):
        return 1
    return 1 + sum(_count_nodes(child) for child in children)


def _count_cases(node: object) -> int:
    if not isinstance(node, dict):
        return 0
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    children = node.get("children") or []
    if not isinstance(children, list):
        children = []
    return int("标题" in _node_tags(data)) + sum(_count_cases(child) for child in children)


def verify_mind_map_readback(
    preview: dict, readback: dict, import_result: dict, mind_map_id: int
) -> dict:
    """Compare the semantic MindNode tree and all six target fields."""
    expected_request = preview["request"]
    expected_root = expected_request["data"]
    actual_root = _readback_root(readback)
    content_errors: list[str] = []
    _compare_nodes(expected_root, actual_root, "root", content_errors)

    if str(readback.get("id")) != str(mind_map_id):
        content_errors.append("METADATA:ID_MISMATCH")
    if _plain_text(readback.get("name")) != _expected_text(expected_request["title"]):
        content_errors.append("METADATA:NAME_MISMATCH")

    target = preview["target"]
    metadata_sources = [readback, import_result]
    association_errors: list[str] = []
    association_missing: list[str] = []
    for field in TARGET_FIELDS:
        actual_values = _lookup_metadata_values(metadata_sources, field)
        if not actual_values:
            association_missing.append(field)
            continue
        right = _normalise_identifier(target[field]) if field.endswith("_id") else str(target[field]).strip()
        for actual in actual_values:
            left = _normalise_identifier(actual) if field.endswith("_id") else str(actual).strip()
            if left != right:
                mismatch = field.upper() + "_MISMATCH"
                if mismatch not in association_errors:
                    association_errors.append(mismatch)

    if content_errors or association_errors:
        status = "NEED_FIX"
    elif association_missing:
        status = "NOT_PROVEN"
    else:
        status = "PASS"

    return {
        "status": status,
        "content_status": "PASS" if not content_errors else "NEED_FIX",
        "association_status": (
            "NEED_FIX" if association_errors else
            "NOT_PROVEN" if association_missing else "PASS"
        ),
        "content_errors": content_errors,
        "association_errors": association_errors,
        "association_missing_fields": association_missing,
        "expected_case_count": len(preview["case_mapping"]),
        "readback_case_count": _count_cases(actual_root),
        "expected_node_count": preview["node_count"],
        "readback_node_count": _count_nodes(actual_root),
        "group_count": len(actual_root.get("children") or []),
    }



def _load_manifest_preflight(preview: dict, evidence: object) -> dict:
    """Read the latest complete Manifest and verify the Markdown snapshot."""
    if not isinstance(evidence, dict):
        raise AceCliError("ACE_PREFLIGHT_MANIFEST_REQUIRED")
    raw_path = evidence.get("path")
    version_id = str(evidence.get("version_id") or "").strip()
    if not isinstance(raw_path, str) or not raw_path.strip() or not version_id:
        raise AceCliError("ACE_PREFLIGHT_MANIFEST_REQUIRED")

    try:
        manifest_path = Path(raw_path).expanduser().resolve(strict=True)
        if manifest_path.name != "manifest.json" or manifest_path.parent.name != version_id:
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_PATH_MISMATCH")
        if manifest_path.parent.parent.name == "versions":
            requirement_root = manifest_path.parent.parent.parent.resolve(strict=True)
        else:
            requirement_root = manifest_path.parent.parent.resolve(strict=True)
        manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

        records = manifest_tools._read_history(requirement_root)
        if not records:
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_HISTORY_EMPTY")
        latest = records[-1]
        if latest["version_id"] != version_id or Path(latest["manifest_path"]).resolve() != manifest_path:
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_NOT_LATEST")
        data = latest["manifest"]
        if data.get("delivery_status") != "complete":
            raise AceCliError("ACE_DELIVERY_NOT_COMPLETE")
        requirement = data.get("requirement") or {}
        if (
            str(requirement.get("id")) != str(preview["target"]["story_id"])
            or str(requirement.get("name")) != str(preview["target"]["story_name"])
        ):
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_REQUIREMENT_MISMATCH")

        manifest_tools.verify_history_artifact_files(requirement_root, records)
        manifest_tools.verify_history_case_snapshots(requirement_root, records)
        markdown_items = [
            item for item in data.get("artifacts", [])
            if item.get("category") == "testcases" and item.get("role") == "markdown"
        ]
        if len(markdown_items) != 1:
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_MARKDOWN_AMBIGUOUS")
        markdown_path = (
            requirement_root / Path(*str(markdown_items[0]["path"]).split("/"))
        ).resolve()
        markdown_path.relative_to(requirement_root)
        markdown_bytes = markdown_path.read_bytes()
        if hashlib.sha256(markdown_bytes).hexdigest() != markdown_items[0]["sha256"]:
            raise AceCliError("ACE_PREFLIGHT_MANIFEST_MARKDOWN_HASH_MISMATCH")
        markdown_text = markdown_bytes.decode("utf-8-sig")
        markdown_text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
        source_sha = hashlib.sha256(markdown_text.lstrip("\ufeff").encode("utf-8")).hexdigest()
        if source_sha != preview.get("source_markdown_sha256"):
            raise AceCliError("ACE_PREFLIGHT_MARKDOWN_MISMATCH")

        active_case_ids = sorted(
            item["case_id"] for item in data.get("case_snapshot", [])
            if item.get("status") != "retired"
        )
        preview_case_ids = sorted(
            str(item.get("case_id") or "") for item in preview.get("case_mapping", [])
        )
        if (
            len(preview_case_ids) != len(set(preview_case_ids))
            or active_case_ids != preview_case_ids
            or data.get("case_count") != len(preview_case_ids)
        ):
            raise AceCliError("ACE_PREFLIGHT_CASE_SET_MISMATCH")
        return {"version_id": version_id, "manifest_sha256": manifest_sha}
    except AceCliError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, manifest_tools.ManifestError) as exc:
        raise AceCliError("ACE_PREFLIGHT_MANIFEST_INVALID", detail=str(exc)[:200]) from exc


def _validate_preflight(preview: dict, preflight: object, write_authorized: bool) -> dict:
    """Validate explicit authorization, the latest complete Markdown artifact, and target fields."""
    if write_authorized is not True:
        raise AceCliError("ACE_WRITE_NOT_AUTHORIZED")
    if not isinstance(preflight, dict):
        raise AceCliError("ACE_PREFLIGHT_REQUIRED")

    manifest_info = _load_manifest_preflight(preview, preflight.get("manifest"))
    confirmed_target = preflight.get("target")
    if not isinstance(confirmed_target, dict):
        raise AceCliError("ACE_PREFLIGHT_TARGET_MISSING")
    for field in TARGET_FIELDS:
        left = _normalise_identifier(confirmed_target.get(field)) if field.endswith("_id") else str(confirmed_target.get(field) or "").strip()
        right = _normalise_identifier(preview["target"][field]) if field.endswith("_id") else str(preview["target"][field]).strip()
        if left != right:
            raise AceCliError("ACE_PREFLIGHT_TARGET_MISMATCH", detail=field)
    return manifest_info


def import_mind_map(
    markdown: str,
    target: dict,
    *,
    preflight: dict,
    write_authorized: bool,
    executable: str | Path | None = None,
    timeout_seconds: int = 180,
    runner: Runner = subprocess.run,
) -> dict:
    """Create one MindMap and return its creation receipt; do not run post-write readback."""
    normalised_target = _normalise_target(target)
    preview = platform_payloads.build_ace_preview(markdown, normalised_target)
    manifest_info = _validate_preflight(preview, preflight, write_authorized)
    cli = resolve_cli(executable)
    request = preview["request"]

    temp_directory = tempfile.TemporaryDirectory(prefix="qa-agent-ace-")
    cleanup_warning = None
    try:
        temp_dir = temp_directory.name
        case_file = Path(temp_dir) / "mindnode.json"
        case_file.write_text(
            json.dumps(request["data"], ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        import_args = [
            "import",
            "--case", str(case_file),
            "--title", request["title"],
            "--product-id", str(request["product_id"]),
            "--dir-id", str(request["dir_id"]),
            "--project-id", str(request["project_id"]),
            "--project-name", str(request["project_name"]),
            "--story-id", str(request["story_id"]),
            "--story-name", str(request["story_name"]),
        ]
        # Recheck that the same latest complete formal Markdown is still current.
        latest_manifest_info = _load_manifest_preflight(
            preview, preflight.get("manifest")
        )
        if latest_manifest_info != manifest_info:
            raise AceCliError("ACE_PREFLIGHT_SNAPSHOT_CHANGED")

        import_result = _run_json(
            import_args,
            executable=cli,
            timeout_seconds=timeout_seconds,
            runner=runner,
            write_operation=True,
        )
        receipt_success_confirmed = _validate_import_receipt(import_result)
        try:
            mind_map_id = extract_created_mind_map_id(import_result)
        except AceCliError as exc:
            raise AceCliError(
                "ACE_IMPORT_OUTCOME_UNKNOWN",
                unknown_outcome=True,
                detail=exc.detail or exc.code,
            ) from exc

        readback_verification = None
        if not receipt_success_confirmed:
            try:
                readback = get_mind_map(mind_map_id, executable=cli, runner=runner)
            except AceCliError as exc:
                raise AceCliError(
                    "ACE_IMPORT_READBACK_FAILED",
                    unknown_outcome=True,
                    detail=f"MindMap ID={mind_map_id}; {exc.code}: {exc.detail}",
                    mind_map_id=mind_map_id,
                ) from exc

            verification = verify_mind_map_readback(
                preview, readback, import_result, mind_map_id
            )
            if (
                verification["content_status"] != "PASS"
                or verification["association_status"] == "NEED_FIX"
            ):
                raise AceCliError(
                    "ACE_IMPORT_READBACK_MISMATCH",
                    status="NEED_FIX",
                    mind_map_id=mind_map_id,
                    detail=(
                        f"MindMap ID={mind_map_id}; "
                        f"content_errors={verification['content_errors']}; "
                        f"association_errors={verification['association_errors']}"
                    ),
                )
            readback_verification = {
                "content_status": verification["content_status"],
                "association_status": verification["association_status"],
                "association_missing_fields": verification["association_missing_fields"],
                "expected_case_count": verification["expected_case_count"],
                "readback_case_count": verification["readback_case_count"],
                "expected_node_count": verification["expected_node_count"],
                "readback_node_count": verification["readback_node_count"],
            }
    except BaseException:
        # Preserve the original import/validation error if best-effort cleanup also fails.
        try:
            temp_directory.cleanup()
        except Exception:
            pass
        raise
    else:
        # A confirmed platform creation must not be reported as failed because local
        # temporary-file cleanup failed after the remote write completed.
        try:
            temp_directory.cleanup()
        except Exception as exc:
            cleanup_warning = type(exc).__name__

    result = {
        "status": "SUCCESS",
        "mind_map_id": mind_map_id,
        "url": import_result.get("url") if isinstance(import_result, dict) else None,
        "confirmation_method": (
            "CREATE_RECEIPT" if receipt_success_confirmed else "ID_READBACK"
        ),
        "case_count": len(preview["case_mapping"]),
        "node_count": preview["node_count"],
        "payload_sha256": preview["payload_sha256"],
        "retry_allowed": False,
        "case_mapping": preview["case_mapping"],
    }
    if cleanup_warning:
        result["cleanup_warning"] = "ACE_TEMP_CLEANUP_FAILED"
        result["cleanup_detail"] = cleanup_warning
    if readback_verification is not None:
        result["readback_verification"] = readback_verification
    return result


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise AceCliError("ACE_PREFLIGHT_JSON_INVALID")
    return value


def _emit(value: object) -> None:
    # ASCII JSON is safe for Windows consoles using GBK or other legacy code pages.
    print(json.dumps(value, ensure_ascii=True, indent=2))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="新版 QA Agent ACE CLI 适配器")
    sub = parser.add_subparsers(dest="command", required=True)

    projects = sub.add_parser("projects", help="读取 ACE 项目列表")
    projects.add_argument("--cli-executable")

    directories = sub.add_parser("directories", help="读取 ACE 项目目录树")
    directories.add_argument("--project-id", required=True)
    directories.add_argument("--cli-executable")

    read = sub.add_parser("read", help="按已知 MindMap ID 回读完整导图")
    read.add_argument("--case-id", required=True)
    read.add_argument("--cli-executable")

    create = sub.add_parser("import", help="创建一张需求 MindMap 并返回平台 ID")
    create.add_argument("--markdown", required=True, type=Path)
    create.add_argument("--product-id", required=True)
    create.add_argument("--dir-id", required=True)
    create.add_argument("--project-id", required=True)
    create.add_argument("--project-name", required=True)
    create.add_argument("--story-id", required=True)
    create.add_argument("--story-name", required=True)
    create.add_argument("--preflight-json", required=True, type=Path)
    create.add_argument("--write-authorized", action="store_true")
    create.add_argument("--timeout-seconds", type=int, default=180)
    create.add_argument("--cli-executable")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "projects":
            _emit(list_projects(executable=args.cli_executable))
            return 0
        if args.command == "directories":
            tree = get_project_directories(args.project_id, executable=args.cli_executable)
            _emit({"tree": tree, "directories": flatten_directory_tree(tree)})
            return 0
        if args.command == "read":
            _emit(get_mind_map(args.case_id, executable=args.cli_executable))
            return 0
        markdown = args.markdown.read_text(encoding="utf-8-sig")
        target = {
            "product_id": args.product_id,
            "dir_id": args.dir_id,
            "project_id": args.project_id,
            "project_name": args.project_name,
            "story_id": args.story_id,
            "story_name": args.story_name,
        }
        result = import_mind_map(
            markdown,
            target,
            preflight=_load_json(args.preflight_json),
            write_authorized=args.write_authorized,
            executable=args.cli_executable,
            timeout_seconds=args.timeout_seconds,
        )
        _emit(result)
        return 0 if result["status"] in {"SUCCESS", "PASS"} else 4 if result["status"] == "NOT_PROVEN" else 1
    except AceCliError as exc:
        error_result = {
            "status": exc.status or ("UNKNOWN_OUTCOME" if exc.unknown_outcome else "FAIL"),
            "code": exc.code,
            "detail": exc.detail,
            "retry_allowed": False,
        }
        if exc.mind_map_id is not None:
            error_result["mind_map_id"] = exc.mind_map_id
        _emit(error_result)
        if exc.unknown_outcome:
            return 3
        return 1 if exc.status == "NEED_FIX" else 2
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _emit({"status": "FAIL", "code": "ACE_ADAPTER_INPUT_INVALID", "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
