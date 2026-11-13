"""Lightweight identity, revision and version-ledger primitives for P1.

AI decides semantic case matching and change classification. This module only
validates those decisions and handles deterministic identity/history metadata.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

try:
    import artifacts
    import xmind
except ImportError:
    from . import artifacts, xmind


SCHEMA_VERSION = "1"
BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
VERSION_RE = re.compile(r"^(\d{8})-v([1-9]\d*)$")
CASE_ID_RE = re.compile(r"^QA-(\d+)-([0-9a-f]{10})$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED_COMPONENT = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)
WINDOWS_PATH_COMPONENT_INVALID = re.compile(r'[<>:"\\|?*\x00-\x1f]')
CATEGORIES = {"testcases", "sql", "api-automation", "test-impact-analysis"}
CATEGORY_DIRECTORY_ALIASES = {"test-impact-analysis": {"analysis", "test-impact-analysis"}}
CASE_STATUSES = {"added", "updated", "unchanged", "retired"}
ARTIFACT_CHANGES = {"added", "updated", "unchanged"}


class ManifestError(ValueError):
    """A manifest or version-history invariant is not satisfied."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _nonempty(value: object, where: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{where} 必须为非空字符串")
    return value.strip()


def _category_directory_matches(category: str, directory: str) -> bool:
    """Accept canonical artifact directories and their legacy category-named path."""
    allowed = CATEGORY_DIRECTORY_ALIASES.get(category, {category})
    return directory in allowed


def _version_parts(value: object) -> tuple[str, int]:
    _require(isinstance(value, str), "version_id 必须为字符串")
    match = VERSION_RE.fullmatch(value)
    _require(match is not None, f"非法版本号：{value}")
    try:
        datetime.strptime(match[1], "%Y%m%d")
    except ValueError as exc:
        raise ManifestError(f"非法版本日期：{match[1]}") from exc
    return match[1], int(match[2])


def validate_case_id(value: object, requirement_id: str) -> str:
    _require(isinstance(value, str), "Case ID 必须为字符串")
    match = CASE_ID_RE.fullmatch(value)
    _require(match is not None, f"Case ID 格式错误：{value}")
    _require(match[1] == requirement_id, f"Case ID 需求编号不一致：{value}")
    return value


WINDOWS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def requirement_directory_name(requirement_id: str, requirement_name: str) -> str:
    """Build the stable requirement archive folder name without losing readable text."""
    _require(
        isinstance(requirement_id, str) and re.fullmatch(r"\d+", requirement_id) is not None,
        "需求编号必须为数字字符串",
    )
    name = _nonempty(requirement_name, "requirement.name")
    safe_name = WINDOWS_INVALID_CHARS.sub("_", name).rstrip(" .")
    safe_name = re.sub(r"_+", "_", safe_name).strip(" ._")
    _require(bool(safe_name), "需求名称清理后为空，无法建立归档目录")
    return f"{requirement_id}-{safe_name}"


def module_directory_name(requirement_name: str) -> str:
    """Return the first full-width bracket module, preserving its brackets."""
    name = _nonempty(requirement_name, "requirement.name")
    match = re.search(r"【([^】]+)】", name)
    module_label = match.group(1).strip() if match else ""
    module = f"【{module_label}】" if module_label else "【未分类】"
    safe_name = WINDOWS_INVALID_CHARS.sub("_", module).rstrip(" .")
    safe_name = re.sub(r"_+", "_", safe_name).strip(" ._")
    if not safe_name or WINDOWS_RESERVED_COMPONENT.fullmatch(safe_name):
        return "【未分类】"
    return safe_name


def requirement_archive_relative_path(requirement_id: str, requirement_name: str) -> str:
    """Return module/requirement while keeping the full original bracketed requirement name."""
    return (
        f"{module_directory_name(requirement_name)}/"
        f"{requirement_directory_name(requirement_id, requirement_name)}"
    )


def generate_case_ids(requirement_id: str, used_ids=(), count: int = 1) -> list[str]:
    """Generate permanent IDs; callers supply all known historical identities."""
    _require(
        isinstance(requirement_id, str) and re.fullmatch(r"\d+", requirement_id) is not None,
        "需求编号必须为数字字符串",
    )
    _require(
        isinstance(count, int) and not isinstance(count, bool) and 1 <= count <= 1000,
        "Case ID 数量必须为 1..1000 的整数",
    )
    used_values = list(used_ids)
    for value in used_values:
        validate_case_id(value, requirement_id)
    used = set(used_values)
    generated = []
    while len(generated) < count:
        candidate = f"QA-{requirement_id}-{secrets.token_hex(5)}"
        if candidate not in used and candidate not in generated:
            generated.append(candidate)
    return generated


def case_fingerprint(case: dict) -> str:
    """Hash user-visible case content; group and ordering are intentionally excluded."""
    _require(isinstance(case, dict), "用例内容必须为对象")
    projection = {
        key: case.get(key)
        for key in ("title", "priority", "precondition", "test_data", "steps")
    }
    payload = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: object, where: str) -> tuple[str, ...]:
    _nonempty(value, where)
    _require("\\" not in value and ":" not in value, f"{where} 必须使用安全的 POSIX 相对路径")
    path = PurePosixPath(value)
    parts = path.parts
    _require(
        not path.is_absolute()
        and bool(parts)
        and all(part not in {"", ".", ".."} for part in parts),
        f"{where} 不能是绝对路径或包含路径穿越",
    )
    _require(path.as_posix() == value, f"{where} 路径格式不规范")
    for part in parts:
        _require(
            not part.endswith((" ", ".")),
            f"{where} 包含 Windows 规范化后可能改变含义的尾随空格或点",
        )
        _require(
            WINDOWS_PATH_COMPONENT_INVALID.search(part) is None,
            f"{where} 包含 Windows 不允许的路径字符",
        )
        _require(
            WINDOWS_RESERVED_COMPONENT.fullmatch(part) is None,
            f"{where} 包含 Windows 保留设备名",
        )
    return parts


def validate_manifest(data: object, requirement_id: str | None = None) -> dict:
    """Validate manifest shape and internal consistency, not business semantics."""
    _require(isinstance(data, dict), "Manifest 顶层必须为 JSON 对象")
    _require(data.get("schema_version") == SCHEMA_VERSION, "不支持的 Manifest schema_version")
    req = data.get("requirement")
    _require(isinstance(req, dict), "Manifest 缺少 requirement 对象")
    req_id = _nonempty(req.get("id"), "requirement.id")
    _require(re.fullmatch(r"\d+", req_id) is not None, "requirement.id 必须为数字字符串")
    _nonempty(req.get("name"), "requirement.name")
    if requirement_id is not None:
        _require(req_id == requirement_id, "Manifest 需求编号与目录不一致")

    version_id = _nonempty(data.get("version_id"), "version_id")
    version_date, version_sequence = _version_parts(version_id)
    created_at = _nonempty(data.get("created_at"), "created_at")
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError as exc:
        raise ManifestError("created_at 不是有效 ISO 8601 时间") from exc
    _require(
        created.tzinfo is not None and created.utcoffset() == timedelta(hours=8),
        "created_at 必须保留北京时间 +08:00 时区偏移",
    )
    _require(
        created.strftime("%Y%m%d") == version_date,
        "version_id 日期必须与 created_at 北京日期一致",
    )
    delivery_status = data.get("delivery_status")
    _require(
        isinstance(delivery_status, str) and delivery_status in {"complete", "partial"},
        "delivery_status 必须为 complete 或 partial",
    )

    artifacts_list = data.get("artifacts")
    _require(
        isinstance(artifacts_list, list) and bool(artifacts_list),
        "Manifest 至少需要一项有效正式产物",
    )
    artifact_keys = set()
    testcase_roles = set()
    for index, item in enumerate(artifacts_list, 1):
        at = f"artifacts[{index}]"
        _require(isinstance(item, dict), f"{at} 必须为对象")
        category = _nonempty(item.get("category"), at + ".category")
        _require(category in CATEGORIES, f"{at}.category 不受支持：{category}")
        role = _nonempty(item.get("role"), at + ".role")
        if category == "testcases":
            testcase_roles.add(role)
        key = (category, role)
        _require(key not in artifact_keys, f"{at} category/role 重复")
        artifact_keys.add(key)
        path_parts = _safe_relative_path(item.get("path"), at + ".path")
        source_version = _nonempty(item.get("source_version"), at + ".source_version")
        source_date, source_sequence = _version_parts(source_version)
        _require(
            (source_date, source_sequence) <= (version_date, version_sequence),
            f"{at}.source_version 不能引用未来版本",
        )
        new_layout = (
            len(path_parts) >= 3
            and _category_directory_matches(category, path_parts[0])
            and path_parts[1] == source_version
        )
        legacy_layout = (
            len(path_parts) >= 3
            and path_parts[0] == source_version
            and _category_directory_matches(category, path_parts[1])
        )
        _require(
            new_layout or legacy_layout,
            f"{at}.path 不在该产物分类允许的目录下：应为分类/source_version/文件路径（或兼容旧版 source_version/分类/文件路径）",
        )
        change = item.get("change")
        _require(isinstance(change, str) and change in ARTIFACT_CHANGES, f"{at}.change 非法")
        if change in {"added", "updated"}:
            _require(source_version == version_id, f"{at} 新增/更新产物必须保存在当前版本目录")
        else:
            _require(source_version != version_id, f"{at} 未变化产物必须引用历史来源版本")
        _require(
            isinstance(item.get("sha256"), str) and SHA256_RE.fullmatch(item["sha256"]) is not None,
            f"{at}.sha256 必须为小写 SHA-256",
        )
    if testcase_roles:
        _require(
            testcase_roles == {"markdown", "xmind", "oracle"},
            "testcases 产物必须完整包含 markdown、xmind、oracle",
        )

    snapshot = data.get("case_snapshot")
    _require(isinstance(snapshot, list), "case_snapshot 必须为数组")
    case_ids = set()
    active_count = retired_count = 0
    for index, item in enumerate(snapshot, 1):
        at = f"case_snapshot[{index}]"
        _require(isinstance(item, dict), f"{at} 必须为对象")
        case_id = validate_case_id(item.get("case_id"), req_id)
        _require(case_id not in case_ids, f"{at}.case_id 重复：{case_id}")
        case_ids.add(case_id)
        revision = item.get("revision")
        _require(
            isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1,
            f"{at}.revision 必须为正整数",
        )
        status = item.get("status")
        _require(isinstance(status, str) and status in CASE_STATUSES, f"{at}.status 非法")
        _require(
            isinstance(item.get("content_sha256"), str)
            and SHA256_RE.fullmatch(item["content_sha256"]) is not None,
            f"{at}.content_sha256 必须为小写 SHA-256",
        )
        derived = item.get("derived_from", [])
        _require(
            isinstance(derived, list) and all(isinstance(x, str) for x in derived),
            f"{at}.derived_from 必须为字符串数组",
        )
        _require(len(derived) == len(set(derived)), f"{at}.derived_from 存在重复 ID")
        for source_id in derived:
            validate_case_id(source_id, req_id)
            _require(source_id != case_id, f"{at}.derived_from 不能引用自身")
        if status == "retired":
            retired_count += 1
            _nonempty(item.get("retirement_reason"), at + ".retirement_reason")
        else:
            active_count += 1

    case_count = data.get("case_count")
    retired_case_count = data.get("retired_case_count")
    _require(
        isinstance(case_count, int)
        and not isinstance(case_count, bool)
        and case_count == active_count,
        "case_count 与有效用例身份快照不一致",
    )
    _require(
        isinstance(retired_case_count, int)
        and not isinstance(retired_case_count, bool)
        and retired_case_count == retired_count,
        "retired_case_count 与退役身份快照不一致",
    )
    if active_count:
        _require(
            testcase_roles == {"markdown", "xmind", "oracle"},
            "存在有效用例身份时必须保留完整 testcases 产物",
        )
    validation = data.get("validation", {})
    _require(isinstance(validation, dict), "validation 必须为对象")
    for key, value in validation.items():
        _nonempty(key, "validation key")
        _nonempty(value, f"validation.{key}")

    changes = data.get("case_changes")
    if changes is not None:
        _require(isinstance(changes, dict), "case_changes 必须为对象")
        added = changes.get("added", [])
        updated = changes.get("updated", [])
        retired = changes.get("retired", [])
        _require(
            isinstance(added, list) and isinstance(updated, list) and isinstance(retired, list),
            "case_changes.added/updated/retired 必须为数组",
        )
        changed_ids = set()
        for case_id in added:
            validate_case_id(case_id, req_id)
            _require(case_id not in changed_ids, "case_changes 存在重复 Case ID")
            changed_ids.add(case_id)
            _require(
                next((x for x in snapshot if x["case_id"] == case_id), {}).get("status") == "added",
                "case_changes.added 与 case_snapshot 不一致",
            )
        for item in updated:
            _require(isinstance(item, dict), "case_changes.updated 项必须为对象")
            case_id = validate_case_id(item.get("case_id"), req_id)
            _require(case_id not in changed_ids, "case_changes 存在重复 Case ID")
            changed_ids.add(case_id)
            before, after = item.get("from_revision"), item.get("to_revision")
            _require(
                isinstance(before, int)
                and not isinstance(before, bool)
                and isinstance(after, int)
                and not isinstance(after, bool)
                and before >= 1
                and after == before + 1,
                "case_changes.updated Revision 必须从旧值递增 1",
            )
            snap = next((x for x in snapshot if x["case_id"] == case_id), {})
            _require(
                snap.get("status") == "updated" and snap.get("revision") == after,
                "case_changes.updated 与 case_snapshot 不一致",
            )
        for item in retired:
            _require(isinstance(item, dict), "case_changes.retired 项必须为对象")
            case_id = validate_case_id(item.get("case_id"), req_id)
            _require(case_id not in changed_ids, "case_changes 存在重复 Case ID")
            changed_ids.add(case_id)
            _nonempty(item.get("reason"), "case_changes.retired.reason")
            snap = next((x for x in snapshot if x["case_id"] == case_id), {})
            _require(snap.get("status") == "retired", "case_changes.retired 与 case_snapshot 不一致")
        _require(bool(changed_ids), "case_changes 为空时应省略该字段")

    return data


def _validate_history_artifact_sources(records: list[dict]) -> None:
    """Verify source Manifest registration without rereading any history files."""
    records_by_version = {record["version_id"]: record for record in records}
    for record in records:
        for item in record["manifest"]["artifacts"]:
            source_version = item["source_version"]
            source_record = records_by_version.get(source_version)
            _require(source_record is not None, f"产物来源版本不存在：{source_version}")
            source_item = next(
                (
                    candidate
                    for candidate in source_record["manifest"]["artifacts"]
                    if candidate["category"] == item["category"]
                    and candidate["role"] == item["role"]
                ),
                None,
            )
            _require(
                source_item is not None
                and source_item["source_version"] == source_version
                and source_item["change"] in {"added", "updated"}
                and source_item["path"] == item["path"]
                and source_item["sha256"] == item["sha256"],
                f"产物来源追溯与来源 Manifest 未登记内容不一致：{source_version}/{item['category']}/{item['role']}",
            )


def _manifest_path_for_version(requirement_root: Path, version_id: str) -> Path:
    """Resolve a new-layout Manifest, falling back to the legacy version-root layout."""
    root = Path(requirement_root)
    current = root / "versions" / version_id / "manifest.json"
    legacy = root / version_id / "manifest.json"
    _require(
        not (current.exists() and legacy.exists()),
        f"同一正式版本同时存在新旧 Manifest，拒绝猜测：{version_id}",
    )
    if current.exists() or (root / "versions" / version_id).exists():
        return current
    return legacy

def _require_writable_requirement_root(requirement_root: Path) -> None:
    """Keep legacy version-first archives readable but prevent new writes into them."""
    root = Path(requirement_root)
    if not root.is_dir() or (root / "versions").is_dir():
        return
    legacy_versions = [
        entry
        for entry in root.iterdir()
        if entry.is_dir() and VERSION_RE.fullmatch(entry.name)
    ]
    _require(
        not legacy_versions,
        "旧版需求归档根目录仅支持只读兼容；请使用模块分组后的需求根目录进行正式发布",
    )


def _read_history(requirement_root: Path) -> list[dict]:
    root = Path(requirement_root)
    if not root.exists():
        return []
    _require(root.is_dir(), "需求归档根路径不是目录")
    records = []
    requirement_id = None
    for version_id in sorted(_version_directory_ids(root), key=_version_parts):
        manifest_path = _manifest_path_for_version(root, version_id)
        _require(manifest_path.is_file(), f"正式版本目录缺少 manifest.json：{version_id}")
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ManifestError(f"无法读取版本 Manifest：{manifest_path}") from exc
        validate_manifest(data, requirement_id)
        _require(
            data["version_id"] == version_id,
            f"Manifest version_id 与目录名不一致：{version_id}",
        )
        if requirement_id is None:
            requirement_id = data["requirement"]["id"]
        records.append({
            "version_id": data["version_id"],
            "date": _version_parts(data["version_id"])[0],
            "sequence": _version_parts(data["version_id"])[1],
            "manifest": data,
            "manifest_path": manifest_path,
            "version_path": manifest_path.parent,
        })
    records.sort(key=lambda x: (x["date"], x["sequence"]))
    _validate_history_artifact_sources(records)
    _validate_history_transitions(records)
    return records


def _version_directory_ids(requirement_root: Path) -> set[str]:
    """Return formal version IDs from new and legacy locations, rejecting duplicates."""
    root = Path(requirement_root)
    if not root.exists():
        return set()
    _require(root.is_dir(), "需求归档根路径不是目录")
    found = {}
    for parent in (root / "versions", root):
        if not parent.is_dir():
            continue
        for entry in parent.iterdir():
            if parent == root and entry.name == "versions":
                continue
            if not entry.is_dir() or VERSION_RE.fullmatch(entry.name) is None:
                continue
            _require(
                entry.name not in found,
                f"同一正式版本同时存在新旧目录，拒绝猜测：{entry.name}",
            )
            found[entry.name] = entry
    return set(found)


def _validate_history_transitions(records: list[dict]) -> None:
    """Verify that every version carries forward the complete identity ledger."""
    previous = None
    seen_ids = set()
    last_created = None
    sequences_by_date = {}
    for record in records:
        data = record["manifest"]
        sequences_by_date.setdefault(record["date"], []).append(record["sequence"])
        created = datetime.fromisoformat(data["created_at"])
        if last_created is not None:
            _require(created >= last_created, "正式版本 created_at 时间顺序倒退")
        last_created = created

        current_items = data["case_snapshot"]
        current = {item["case_id"]: item for item in current_items}
        changes = data.get("case_changes") or {}
        added = set(changes.get("added", []))
        updated = {item["case_id"]: item for item in changes.get("updated", [])}
        retired = {item["case_id"]: item for item in changes.get("retired", [])}

        if previous is None:
            _require(not updated and not retired, "首个正式版本不能包含修改或退役记录")
            _require(
                all(
                    item["status"] == "added" and item["revision"] == 1
                    for item in current_items
                ),
                "首个正式版本的用例必须全部从 Revision 1 新增",
            )
            _require(added == set(current), "首个正式版本 case_changes.added 必须覆盖全部用例")
        else:
            for case_id, old in previous.items():
                _require(
                    case_id in current,
                    f"历史 Case ID 未在当前完整身份快照中保留：{case_id}",
                )
                new = current[case_id]
                if old["status"] == "retired":
                    _require(
                        new["status"] == "retired"
                        and new["revision"] == old["revision"]
                        and new.get("retirement_reason") == old.get("retirement_reason")
                        and new["content_sha256"] == old["content_sha256"],
                        f"已退役 Case ID 的身份、状态或内容指纹发生变化：{case_id}",
                    )
                    _require(
                        case_id not in updated and case_id not in retired,
                        f"已退役 Case ID 不得再次变更：{case_id}",
                    )
                elif new["status"] == "updated":
                    change = updated.get(case_id)
                    _require(
                        new["revision"] == old["revision"] + 1
                        and change is not None
                        and change["from_revision"] == old["revision"]
                        and change["to_revision"] == new["revision"]
                        and new["content_sha256"] != old["content_sha256"],
                        f"Revision 更新与上一正式版本不连续：{case_id}",
                    )
                elif new["status"] == "unchanged":
                    _require(
                        new["revision"] == old["revision"] and case_id not in updated,
                        f"未变化用例 Revision 或变更账本不一致：{case_id}",
                    )
                elif new["status"] == "retired":
                    change = retired.get(case_id)
                    _require(
                        new["revision"] == old["revision"]
                        and new["content_sha256"] == old["content_sha256"]
                        and change is not None
                        and change["reason"] == new.get("retirement_reason"),
                        f"用例退役状态、原因或内容指纹与上一正式版本不一致：{case_id}",
                    )
                else:
                    raise ManifestError(f"历史用例不能重新标记为新增：{case_id}")

            new_ids = set(current) - set(previous)
            for case_id in new_ids:
                item = current[case_id]
                _require(
                    case_id not in seen_ids
                    and item["status"] == "added"
                    and item["revision"] == 1
                    and case_id in added,
                    f"新增用例身份或 Revision 不合法：{case_id}",
                )
            expected_updated = {
                case_id for case_id, item in current.items() if item["status"] == "updated"
            }
            expected_retired = {
                case_id
                for case_id, item in current.items()
                if item["status"] == "retired" and previous[case_id]["status"] != "retired"
            }
            _require(added == new_ids, "case_changes.added 与跨版本新增身份不一致")
            _require(
                set(updated) == expected_updated,
                "case_changes.updated 与跨版本 Revision 变化不一致",
            )
            _require(
                set(retired) == expected_retired,
                "case_changes.retired 与跨版本退役变化不一致",
            )

        for item in current_items:
            for source_id in item.get("derived_from", []):
                _require(
                    source_id in seen_ids,
                    f"derived_from 未引用此前正式版本中的历史 Case ID：{source_id}",
                )
        seen_ids.update(current)
        previous = current

    for date, sequences in sequences_by_date.items():
        ordered = sorted(sequences)
        _require(
            ordered == list(range(1, len(ordered) + 1)),
            f"{date} 正式版本序号不连续，历史版本可能缺失",
        )


def historical_case_ids(requirement_root: Path, records: list[dict] | None = None) -> set[str]:
    """Return every identity ever published, including retired identities."""
    records = records if records is not None else _read_history(requirement_root)
    ids = set()
    for record in records:
        ids.update(item["case_id"] for item in record["manifest"]["case_snapshot"])
    return ids


def historical_case_ids_from_manifest(
    requirement_root: Path, requirement_id: str, manifest_path: Path
) -> set[str]:
    """Use the latest complete identity snapshot without rescanning every historical Manifest.

    The publish preflight still validates the entire history before any formal commit.
    """
    root = Path(requirement_root).resolve()
    path = Path(manifest_path).resolve()
    is_new_layout = (
        path.name == "manifest.json"
        and path.parent.parent == root / "versions"
    )
    is_legacy_layout = (
        path.name == "manifest.json"
        and path.parent.parent == root
    )
    _require(
        is_new_layout or is_legacy_layout,
        "基线 Manifest 必须位于需求根目录的 versions/<版本>/ 或旧版 <版本>/ 目录",
    )
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"无法读取基线 Manifest：{path}") from exc
    validate_manifest(data, requirement_id)
    _require(
        data["version_id"] == path.parent.name,
        "基线 Manifest version_id 与目录名不一致",
    )
    version_directories = _version_directory_ids(root)
    _require(bool(version_directories), "需求归档根目录不存在正式版本")
    latest_version = max(version_directories, key=_version_parts)
    _require(path.parent.name == latest_version, "提供的基线 Manifest 不是最新正式版本")
    _require(
        path == _manifest_path_for_version(root, latest_version).resolve(),
        "提供的基线 Manifest 不是当前版本账本文件",
    )
    return {item["case_id"] for item in data["case_snapshot"]}


def load_latest_manifest(
    requirement_root: Path,
    verify_files: bool = True,
    records: list[dict] | None = None,
) -> dict | None:
    records = records if records is not None else _read_history(Path(requirement_root))
    if not records:
        return None
    latest = records[-1]
    if verify_files:
        verify_artifact_files(Path(requirement_root), latest["manifest"])
    return latest


def verify_artifact_files(requirement_root: Path, manifest: dict) -> None:
    root = Path(requirement_root).resolve()
    for item in manifest["artifacts"]:
        parts = _safe_relative_path(item["path"], "artifact.path")
        path = (root / Path(*parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ManifestError("产物路径越界") from exc
        _require(path.is_file(), f"Manifest 引用的正式产物不存在：{item['path']}")
        digest = sha256_file(path)
        _require(digest == item["sha256"], f"产物 SHA-256 不一致：{item['path']}")


def verify_history_artifact_files(
    requirement_root: Path, records: list[dict] | None = None
) -> int:
    """Verify each immutable artifact file once across the complete formal history."""
    root = Path(requirement_root).resolve()
    records = records if records is not None else _read_history(Path(requirement_root))
    expected = {}
    for record in records:
        for item in record["manifest"]["artifacts"]:
            previous_hash = expected.get(item["path"])
            _require(
                previous_hash is None or previous_hash == item["sha256"],
                f"同一历史产物路径出现不同 SHA-256：{item['path']}",
            )
            expected[item["path"]] = item["sha256"]
    for relative, expected_hash in expected.items():
        parts = _safe_relative_path(relative, "artifact.path")
        path = (root / Path(*parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ManifestError("历史产物路径越界") from exc
        _require(path.is_file(), f"历史正式产物不存在：{relative}")
        _require(sha256_file(path) == expected_hash, f"历史正式产物 SHA-256 不一致：{relative}")
    return len(expected)


def _verify_manifest_markdown_requirement(
    manifest_requirement: dict, markdown_requirement: dict, context: str
) -> None:
    """Require the authoritative Markdown identity to match its owning Manifest."""
    _require(
        markdown_requirement["id"] == manifest_requirement["id"],
        f"{context} Markdown 需求编号与 Manifest 不一致",
    )
    _require(
        _nonempty(markdown_requirement["name"], "Markdown requirement.name")
        == _nonempty(manifest_requirement["name"], "Manifest requirement.name"),
        f"{context} Markdown 需求名称与 Manifest 不一致",
    )


def verify_manifest_case_snapshot(
    requirement_root: Path,
    manifest: dict,
    parsed_cache: dict[str, dict] | None = None,
) -> dict | None:
    """Recompute active case fingerprints from the Manifest's authoritative Markdown."""
    root = Path(requirement_root).resolve()
    active = {
        item["case_id"]: item
        for item in manifest["case_snapshot"]
        if item["status"] != "retired"
    }
    markdown_item = next(
        (
            item
            for item in manifest["artifacts"]
            if item["category"] == "testcases" and item["role"] == "markdown"
        ),
        None,
    )
    if markdown_item is None:
        _require(not active, "Manifest 有效用例身份存在，但没有可追溯的 Markdown 产物")
        return None

    parts = _safe_relative_path(markdown_item["path"], "artifact.path")
    markdown_path = (root / Path(*parts)).resolve()
    try:
        markdown_path.relative_to(root)
    except ValueError as exc:
        raise ManifestError("当前有效 Markdown 产物路径越界") from exc

    cache_key = os.path.normcase(str(markdown_path))
    parsed = parsed_cache.get(cache_key) if parsed_cache is not None else None
    if parsed is None:
        try:
            parsed = artifacts.parse_markdown(markdown_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, artifacts.ArtifactError) as exc:
            raise ManifestError(f"历史 testcases.md 无法解析：{markdown_item['path']}") from exc
        if parsed_cache is not None:
            parsed_cache[cache_key] = parsed
    _verify_manifest_markdown_requirement(
        manifest["requirement"], parsed["requirement"], "历史验签"
    )

    actual = {}
    for group in parsed["groups"]:
        for case in group["cases"]:
            case_id = case["case_id"]
            _require(case_id not in actual, f"当前 Markdown 存在重复 Case ID：{case_id}")
            actual[case_id] = case_fingerprint(case)
    _require(
        set(actual) == set(active),
        "当前 Markdown Case ID 集合与 Manifest 有效身份快照不一致",
    )
    for case_id, snapshot in active.items():
        _require(
            actual[case_id] == snapshot["content_sha256"],
            f"当前 Markdown 用例内容指纹与 Manifest 不一致：{case_id}",
        )
    return parsed


def verify_history_case_snapshots(
    requirement_root: Path, records: list[dict]
) -> dict[str, dict]:
    """Verify every historical snapshot, parsing each unique authoritative Markdown once."""
    parsed_cache = {}
    for record in records:
        verify_manifest_case_snapshot(
            requirement_root, record["manifest"], parsed_cache=parsed_cache
        )
    return parsed_cache


def resolve_latest_case_baseline(
    requirement_root: Path,
    records: list[dict] | None = None,
    latest_record: dict | None = None,
    parsed_cache: dict[str, dict] | None = None,
) -> dict | None:
    """Resolve the current baseline, reusing history records and parsed Markdown when available."""
    latest = latest_record
    if latest is None:
        latest = load_latest_manifest(
            requirement_root, verify_files=True, records=records
        )
    if latest is None:
        return None
    manifest = latest["manifest"]
    parsed = verify_manifest_case_snapshot(
        requirement_root, manifest, parsed_cache=parsed_cache
    )
    markdown_item = next(
        (
            item
            for item in manifest["artifacts"]
            if item["category"] == "testcases" and item["role"] == "markdown"
        ),
        None,
    )
    markdown_path = (
        Path(requirement_root).joinpath(
            *_safe_relative_path(markdown_item["path"], "artifact.path")
        )
        if markdown_item
        else None
    )
    return {
        "manifest": manifest,
        "manifest_path": latest["manifest_path"],
        "markdown_path": markdown_path,
        "parsed": parsed,
    }


def build_case_snapshot(
    parsed: dict,
    previous_manifest: dict | None = None,
    historical_ids=(),
    changes: dict | None = None,
    lineage: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Apply AI-supplied change intent; Python validates identity and Revision arithmetic."""
    requirement_id = parsed.get("requirement", {}).get("id")
    _require(
        isinstance(requirement_id, str) and re.fullmatch(r"\d+", requirement_id) is not None,
        "解析结果缺少有效需求编号",
    )
    if changes is None:
        changes = {}
    _require(isinstance(changes, dict), "case_changes 输入必须为对象")
    added_values = changes.get("added", [])
    updated_values = changes.get("updated", [])
    retired_values = changes.get("retired", [])
    _require(
        isinstance(added_values, list)
        and isinstance(updated_values, list)
        and isinstance(retired_values, list),
        "case_changes 输入字段必须为数组",
    )
    _require(
        all(isinstance(x, str) for x in added_values + updated_values),
        "case_changes.added/updated 必须为 Case ID 字符串数组",
    )
    for case_id in added_values + updated_values:
        validate_case_id(case_id, requirement_id)
    added = set(added_values)
    updated = set(updated_values)
    _require(
        len(added) == len(added_values) and len(updated) == len(updated_values),
        "新增/修改 Case ID 存在重复",
    )
    retired = {}
    for item in retired_values:
        _require(isinstance(item, dict), "退役项必须为对象")
        case_id = validate_case_id(item.get("case_id"), requirement_id)
        _require(case_id not in retired, "退役 Case ID 重复")
        retired[case_id] = _nonempty(item.get("reason"), "retired.reason")
    _require(
        not (added & updated or added & set(retired) or updated & set(retired)),
        "新增、修改、退役 Case ID 不能重叠",
    )

    current = []
    for group in parsed.get("groups", []):
        for case in group.get("cases", []):
            case_id = validate_case_id(case.get("case_id"), requirement_id)
            current.append(case)
    current_ids = [case["case_id"] for case in current]
    _require(len(current_ids) == len(set(current_ids)), "当前 Markdown 存在重复 Case ID")
    current_set = set(current_ids)

    base_items = previous_manifest.get("case_snapshot", []) if previous_manifest else []
    _require(isinstance(base_items, list), "历史 Manifest 缺少有效 case_snapshot")
    base = {item["case_id"]: item for item in base_items}
    _require(len(base) == len(base_items), "历史 Manifest 存在重复 Case ID")
    history_values = list(historical_ids)
    for case_id in history_values:
        validate_case_id(case_id, requirement_id)
    history = set(history_values) | set(base)
    if lineage is None:
        lineage = {}
    _require(
        isinstance(lineage, dict) and all(isinstance(key, str) for key in lineage),
        "lineage 必须为字符串 Case ID 到来源数组的对象",
    )
    _require(set(lineage) <= current_set, "lineage 只能引用当前 Markdown 中的用例")

    if previous_manifest is None:
        _require(not updated and not retired, "首次正式版本不能修改或退役历史用例")
        if added:
            _require(added == current_set, "首次版本 added 必须覆盖全部当前用例")
        else:
            added = set(current_set)
        _require(not (history & current_set), "首次版本使用了历史已存在的 Case ID")
    else:
        _require(
            previous_manifest.get("requirement", {}).get("id") == requirement_id,
            "历史 Manifest 与当前需求编号不一致",
        )
        if not base and not history:
            if added:
                _require(added == current_set, "首次出现测试用例时 added 必须覆盖全部当前用例")
            else:
                added = set(current_set)
        for case_id in current_set:
            old = base.get(case_id)
            if old is None:
                _require(case_id not in history, f"Case ID 曾经使用过，禁止复用：{case_id}")
                _require(case_id in added, f"新用例必须明确列入 case_changes.added：{case_id}")
            else:
                _require(old["status"] != "retired", f"已退役 Case ID 不得重新启用：{case_id}")
                _require(case_id not in added, f"历史用例不能标记为新增：{case_id}")
        for case_id, old in base.items():
            if old["status"] == "retired":
                _require(case_id not in current_set, f"已退役 Case ID 不得复用：{case_id}")
            elif case_id not in current_set:
                _require(
                    case_id in retired,
                    f"历史有效用例意外缺失，必须明确退役或保留：{case_id}",
                )
        _require(added <= current_set, "case_changes.added 引用了当前 Markdown 不存在的用例")
        _require(updated <= current_set, "case_changes.updated 引用了当前 Markdown 不存在的用例")
        _require(set(retired) <= set(base), "case_changes.retired 引用了未知历史 Case ID")
        _require(set(retired).isdisjoint(current_set), "退役用例仍出现在当前 Markdown")
        _require(updated <= set(base), "只有历史用例可以标记为修改")
    _require(set(lineage) <= added, "lineage 只能为本次新增用例声明历史来源")

    snapshots = []
    generated_updated = []
    for case in current:
        case_id = case["case_id"]
        old = base.get(case_id)
        if old is None:
            revision, status = 1, "added"
        elif case_id in updated:
            revision, status = old["revision"] + 1, "updated"
            generated_updated.append({
                "case_id": case_id,
                "from_revision": old["revision"],
                "to_revision": revision,
            })
        else:
            revision, status = old["revision"], "unchanged"
        fingerprint = case_fingerprint(case)
        if old is not None and status == "updated":
            _require(
                fingerprint != old["content_sha256"],
                f"用例标记为 updated，但内容指纹未变化：{case_id}",
            )
        item = {
            "case_id": case_id,
            "revision": revision,
            "status": status,
            "content_sha256": fingerprint,
        }
        derived = lineage.get(case_id, old.get("derived_from", []) if old else [])
        _require(
            isinstance(derived, list) and all(isinstance(x, str) for x in derived),
            f"{case_id}.derived_from 必须为字符串数组",
        )
        _require(len(derived) == len(set(derived)), f"{case_id}.derived_from 存在重复 ID")
        if derived:
            for source_id in derived:
                validate_case_id(source_id, requirement_id)
                _require(
                    source_id in history and source_id != case_id,
                    f"{case_id}.derived_from 必须引用真实历史 Case ID",
                )
            item["derived_from"] = derived
        snapshots.append(item)

    generated_retired = []
    for old in base_items:
        case_id = old["case_id"]
        if old["status"] == "retired":
            retired_item = dict(old)
            retired_item["status"] = "retired"
            snapshots.append(retired_item)
        elif case_id in retired:
            retired_item = dict(old)
            retired_item["status"] = "retired"
            retired_item["retirement_reason"] = retired[case_id]
            snapshots.append(retired_item)
            generated_retired.append({"case_id": case_id, "reason": retired[case_id]})

    generated_changes = {}
    generated_added = [case_id for case_id in current_ids if case_id in added]
    if generated_added:
        generated_changes["added"] = generated_added
    if generated_updated:
        generated_changes["updated"] = generated_updated
    if generated_retired:
        generated_changes["retired"] = generated_retired
    return snapshots, generated_changes or None


def next_version_id(
    requirement_root: Path, date: str | None = None, records: list[dict] | None = None
) -> str:
    """Allocate the next same-day sequence, reusing a caller's validated history when available."""
    if date is None:
        date = datetime.now(BEIJING).strftime("%Y%m%d")
    try:
        datetime.strptime(date, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise ManifestError("版本日期必须为有效 YYYYMMDD") from exc
    records = records if records is not None else _read_history(Path(requirement_root))
    same_day = [x["sequence"] for x in records if x["date"] == date]
    return f"{date}-v{max(same_day, default=0) + 1}"


def _effective_artifact_path(
    requirement_root: Path, temporary_version: Path, version_id: str, item: dict
) -> Path:
    parts = _safe_relative_path(item["path"], "artifact.path")
    category = item["category"]
    source_version = item["source_version"]
    if (
        len(parts) >= 3
        and _category_directory_matches(category, parts[0])
        and parts[1] == source_version
    ):
        category_directory, relative_parts = parts[0], parts[2:]
    elif (
        len(parts) >= 3
        and parts[0] == source_version
        and _category_directory_matches(category, parts[1])
    ):
        category_directory, relative_parts = parts[1], parts[2:]
    else:
        raise ManifestError(f"产物路径与分类/来源版本不匹配：{item['path']}")
    if source_version == version_id:
        return temporary_version.joinpath(category_directory, *relative_parts)
    return requirement_root.joinpath(*parts)


def _publish_version_locked(
    requirement_root: Path,
    requirement_id: str,
    requirement_name: str,
    staged_artifacts: list[dict],
    delivery_status: str = "complete",
    case_changes: dict | None = None,
    lineage: dict | None = None,
    retire_artifacts=(),
    created_at: str | None = None,
    expected_base_version: str | None = None,
) -> dict:
    """Publish one immutable requirement version from staged files.

    Unchanged artifacts remain at their original paths and are referenced by
    the new Manifest. A complete version directory becomes visible by one rename.
    """
    _require(
        isinstance(requirement_id, str) and re.fullmatch(r"\d+", requirement_id) is not None,
        "需求编号必须为数字字符串",
    )
    _nonempty(requirement_name, "requirement.name")
    _require(
        isinstance(delivery_status, str) and delivery_status in {"complete", "partial"},
        "delivery_status 必须为 complete 或 partial",
    )
    _require(isinstance(staged_artifacts, list), "staged_artifacts 必须为数组")
    root = Path(requirement_root)
    history_records = _read_history(root)
    _require_writable_requirement_root(root)
    history_version_ids = {record["version_id"] for record in history_records}
    _require(
        _version_directory_ids(root) == history_version_ids,
        "正式版本目录集合与已读取历史不一致，拒绝使用不完整基线发布",
    )

    actual_base_version = history_records[-1]["version_id"] if history_records else None
    _require(
        expected_base_version is None
        or (
            isinstance(expected_base_version, str)
            and VERSION_RE.fullmatch(expected_base_version) is not None
        ),
        "expected_base_version 必须为正式版本号或 null",
    )
    _require(
        expected_base_version == actual_base_version,
        f"发布基线已变化：本次生成预期基线为 {expected_base_version or 'NO_HISTORY'}"
        f"，当前最新版本为 {actual_base_version or 'NO_HISTORY'}"
        "；请重新 inspect 并基于最新基线重建发布输入",
    )
    if history_records:
        verify_history_artifact_files(root, history_records)
        verify_history_case_snapshots(root, history_records)
    previous_record = history_records[-1] if history_records else None
    previous = previous_record["manifest"] if previous_record else None
    if previous is not None:
        _require(
            previous["requirement"]["id"] == requirement_id,
            "历史 Manifest 与当前需求编号不一致",
        )
        _require(
            previous["requirement"]["name"] == requirement_name,
            "历史 Manifest 的需求名称与本次输入不一致",
        )
    history_ids = {
        item["case_id"]
        for record in history_records
        for item in record["manifest"]["case_snapshot"]
    }
    previous_artifacts = {
        (item["category"], item["role"]): item
        for item in (previous["artifacts"] if previous else [])
    }

    staged = {}
    for index, spec in enumerate(staged_artifacts, 1):
        at = f"staged_artifacts[{index}]"
        _require(isinstance(spec, dict), f"{at} 必须为对象")
        category = _nonempty(spec.get("category"), at + ".category")
        _require(category in CATEGORIES, f"{at}.category 不受支持")
        role = _nonempty(spec.get("role"), at + ".role")
        key = (category, role)
        _require(key not in staged, f"{at} category/role 重复")
        parts = _safe_relative_path(spec.get("path"), at + ".path")
        _require(
            len(parts) >= 2 and _category_directory_matches(category, parts[0]),
            f"{at}.path 必须以该产物分类允许的目录开头",
        )
        category_directory = "analysis" if category == "test-impact-analysis" else parts[0]
        relative_path = "/".join((category_directory, *parts[1:]))
        source_value = _nonempty(spec.get("source_path"), at + ".source_path")
        source = Path(source_value)
        if not source.is_absolute():
            source = Path.cwd() / source
        _require(source.is_file(), f"{at}.source_path 不存在或不是文件：{source_value}")
        staged[key] = {
            "category": category,
            "role": role,
            "source": source,
            "relative_path": relative_path,
            "sha256": sha256_file(source),
        }

    _require(isinstance(retire_artifacts, (list, tuple)), "retire_artifacts 必须为数组")
    retired_pairs = set()
    for item in retire_artifacts:
        _require(isinstance(item, dict), "retire_artifacts 项必须为对象")
        pair = (
            _nonempty(item.get("category"), "retire_artifacts.category"),
            _nonempty(item.get("role"), "retire_artifacts.role"),
        )
        _require(pair[0] in CATEGORIES, "retire_artifacts.category 不受支持")
        _require(pair not in retired_pairs, "retire_artifacts 存在重复项")
        _require(pair in previous_artifacts, "不能退役当前 Manifest 中不存在的产物")
        _require(pair not in staged, "同一产物不能同时更新和退役")
        retired_pairs.add(pair)

    inventory = {}
    changed_specs = {}
    for pair, old in previous_artifacts.items():
        if pair not in retired_pairs:
            inventory[pair] = dict(old, change="unchanged")
    for pair, spec in staged.items():
        old = previous_artifacts.get(pair)
        old_parts = _safe_relative_path(old["path"], "previous_artifact.path") if old else ()
        new_parts = _safe_relative_path(spec["relative_path"], "staged_artifact.path")
        old_relative = "/".join(old_parts[2:]) if len(old_parts) >= 3 else None
        new_relative = "/".join(new_parts[1:]) if len(new_parts) >= 2 else None
        if (
            old
            and old["sha256"] == spec["sha256"]
            and old_relative == new_relative
        ):
            inventory[pair] = dict(old, change="unchanged")
        else:
            spec["change"] = "updated" if old else "added"
            changed_specs[pair] = spec

    status_changed = previous is None or previous["delivery_status"] != delivery_status
    _require(
        bool(changed_specs or retired_pairs or status_changed),
        "本次没有实质内容或交付状态变化，不创建新正式版本",
    )
    _require(bool(inventory or changed_specs), "正式版本至少需要保留或新增一项产物")

    created_at = created_at or datetime.now(BEIJING).isoformat(timespec="seconds")
    try:
        created = datetime.fromisoformat(created_at)
    except (TypeError, ValueError) as exc:
        raise ManifestError("created_at 不是有效 ISO 8601 时间") from exc
    _require(
        created.tzinfo is not None and created.utcoffset() == timedelta(hours=8),
        "created_at 必须使用北京时间 +08:00",
    )
    created_date = created.strftime("%Y%m%d")
    if previous_record is not None:
        _require(created_date >= previous_record["date"], "正式版本日期不能早于最新正式版本")
        if created_date == previous_record["date"]:
            previous_created = datetime.fromisoformat(
                previous_record["manifest"]["created_at"]
            )
            _require(created >= previous_created, "同日正式版本 created_at 不能早于最新版本")
    version_id = next_version_id(root, created_date, records=history_records)
    root.mkdir(parents=True, exist_ok=True)
    work_root = root / ".qa-work"
    _require(not work_root.exists() or work_root.is_dir(), ".qa-work 已存在但不是目录")
    work_root.mkdir(exist_ok=True)
    temporary_version = Path(tempfile.mkdtemp(prefix=f".{version_id}-", dir=work_root))
    versions_root = root / "versions"
    final_version = versions_root / version_id
    moved_category_dirs = []
    manifest_stage_dir = None
    committed = False

    try:
        for pair, spec in changed_specs.items():
            temporary_root = temporary_version.resolve()
            destination = temporary_version.joinpath(
                *spec["relative_path"].split("/")
            ).resolve()
            try:
                destination.relative_to(temporary_root)
            except ValueError as exc:
                raise ManifestError("暂存产物目标路径规范化后越界") from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(spec["source"], destination)
            copied_hash = sha256_file(destination)
            _require(
                copied_hash == spec["sha256"],
                f"暂存期间源文件发生变化，拒绝发布：{spec['source']}",
            )
            inventory[pair] = {
                "category": spec["category"],
                "role": spec["role"],
                "path": (
                    f"{spec['relative_path'].split('/')[0]}/{version_id}/"
                    f"{'/'.join(spec['relative_path'].split('/')[1:])}"
                ),
                "source_version": version_id,
                "change": spec["change"],
                "sha256": copied_hash,
            }

        artifacts_list = sorted(
            inventory.values(), key=lambda x: (x["category"], x["role"])
        )
        testcase_items = [x for x in artifacts_list if x["category"] == "testcases"]
        validation = {}
        if testcase_items:
            roles = {x["role"] for x in testcase_items}
            _require(
                roles == {"markdown", "xmind", "oracle"},
                "testcases 产物必须完整包含 markdown、xmind、oracle",
            )
            by_role = {x["role"]: x for x in testcase_items}
            md_path = _effective_artifact_path(
                root, temporary_version, version_id, by_role["markdown"]
            )
            xmind_path = _effective_artifact_path(
                root, temporary_version, version_id, by_role["xmind"]
            )
            oracle_path = _effective_artifact_path(
                root, temporary_version, version_id, by_role["oracle"]
            )
            try:
                markdown_text = md_path.read_text(encoding="utf-8-sig")
                oracle_data = json.loads(oracle_path.read_text(encoding="utf-8-sig"))
                parsed = artifacts.parse_markdown(markdown_text)
                pair_report = artifacts.check_pair(markdown_text, oracle_data)
                _verify_manifest_markdown_requirement(
                    {"id": requirement_id, "name": requirement_name},
                    pair_report["requirement"],
                    "正式发布",
                )
                xmind_report = xmind.verify_xmind(parsed, xmind_path)
            except (OSError, UnicodeError, json.JSONDecodeError, artifacts.ArtifactError) as exc:
                raise ManifestError(f"正式用例产物一致性校验失败：{exc}") from exc
            _require(
                pair_report["result"] == "STRUCTURE_PASS",
                "Markdown/Oracle 结构校验未通过",
            )
            _require(
                xmind_report["result"] == "XMIND_READBACK_PASS",
                "XMind 实际回读未通过",
            )
            case_snapshot, generated_changes = build_case_snapshot(
                parsed, previous, history_ids, case_changes, lineage
            )
            validation = {
                "markdown_oracle": "STRUCTURE_PASS",
                "xmind_readback": "XMIND_READBACK_PASS",
                "semantic_review": "NOT_AUTOMATED",
            }
        else:
            testcase_roles = {"markdown", "xmind", "oracle"}
            retire_testcase_bundle = {
                ("testcases", role) for role in testcase_roles
            } <= retired_pairs
            if retire_testcase_bundle:
                empty_parsed = {
                    "requirement": {"id": requirement_id, "name": requirement_name},
                    "groups": [],
                }
                case_snapshot, generated_changes = build_case_snapshot(
                    empty_parsed, previous, history_ids, case_changes, lineage
                )
            else:
                _require(
                    not case_changes and not lineage,
                    "发生用例变化时必须提供完整 testcases 产物",
                )
                case_snapshot = []
                if previous:
                    for old in previous["case_snapshot"]:
                        item = dict(old)
                        if item["status"] != "retired":
                            item["status"] = "unchanged"
                        case_snapshot.append(item)
                generated_changes = None

        manifest_data = {
            "schema_version": SCHEMA_VERSION,
            "requirement": {"id": requirement_id, "name": requirement_name},
            "version_id": version_id,
            "created_at": created,
            "delivery_status": delivery_status,
            "artifacts": artifacts_list,
            "case_snapshot": case_snapshot,
            "case_count": sum(x["status"] != "retired" for x in case_snapshot),
            "retired_case_count": sum(x["status"] == "retired" for x in case_snapshot),
            "validation": validation,
        }
        manifest_data["created_at"] = created.isoformat(timespec="seconds")
        if generated_changes:
            manifest_data["case_changes"] = generated_changes
        validate_manifest(manifest_data, requirement_id)

        manifest_path = temporary_version / "manifest.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n")

        for item in artifacts_list:
            path = _effective_artifact_path(root, temporary_version, version_id, item)
            _require(path.is_file(), f"发布前产物缺失：{item['path']}")
            _require(
                sha256_file(path) == item["sha256"],
                f"发布前产物 SHA-256 不一致：{item['path']}",
            )

        _require(
            _version_directory_ids(root) == history_version_ids,
            "正式版本目录集合在发布准备期间发生变化，拒绝提交",
        )
        _require(not final_version.exists(), f"正式版本目录已存在，拒绝覆盖：{version_id}")
        category_directories = sorted({
            spec["relative_path"].split("/")[0]
            for spec in changed_specs.values()
        })
        for category_directory in category_directories:
            category_parent = root / category_directory
            category_target = category_parent / version_id
            _require(
                not category_target.exists(),
                f"该分类的目标版本目录已存在，拒绝覆盖：{category_target}",
            )
        versions_root.mkdir(parents=True, exist_ok=True)
        manifest_stage_dir = Path(
            tempfile.mkdtemp(prefix=f".{version_id}-", dir=versions_root)
        )
        shutil.copyfile(manifest_path, manifest_stage_dir / "manifest.json")
        for category_directory in category_directories:
            staged_category = temporary_version / category_directory
            if not staged_category.is_dir():
                continue
            category_parent = root / category_directory
            category_parent.mkdir(parents=True, exist_ok=True)
            category_target = category_parent / version_id
            os.rename(staged_category, category_target)
            moved_category_dirs.append(category_target)
        for item in artifacts_list:
            parts = _safe_relative_path(item["path"], "artifact.path")
            published_path = root.joinpath(*parts)
            _require(published_path.is_file(), f"提交前产物缺失：{item['path']}")
            _require(
                sha256_file(published_path) == item["sha256"],
                f"提交前产物 SHA-256 不一致：{item['path']}",
            )
        os.rename(manifest_stage_dir, final_version)
        manifest_stage_dir = None
        committed = True
        try:
            manifest_path = final_version / "manifest.json"
            published_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            validate_manifest(published_data, requirement_id)
            _require(
                published_data["version_id"] == version_id,
                "发布后 Manifest version_id 回读不一致",
            )
            _require(published_data == manifest_data, "发布后 Manifest 内容回读不一致")
            actual_version_ids = _version_directory_ids(root)
            _require(
                actual_version_ids == (history_version_ids | {version_id}),
                "发布后正式版本目录集合与本次预期不一致，可能存在并发或外部写入",
            )
            published_record = {
                "version_id": version_id,
                "date": _version_parts(version_id)[0],
                "sequence": _version_parts(version_id)[1],
                "manifest": published_data,
                "manifest_path": manifest_path,
                "version_path": final_version,
            }
            committed_records = [*history_records, published_record]
            _validate_history_artifact_sources(committed_records)
            _validate_history_transitions(committed_records)
            verify_artifact_files(root, published_data)
            resolve_latest_case_baseline(root, latest_record=published_record)
        except Exception as exc:
            raise ManifestError(
                f"版本目录已发布，但发布后回读验签失败；请核对 {final_version}，不要直接重试：{exc}"
            ) from exc
        return {
            "result": "MANIFEST_PUBLISH_PASS",
            "version_id": version_id,
            "version_path": str(final_version),
            "manifest": manifest_data,
        }
    finally:
        if not committed:
            for category_path in reversed(moved_category_dirs):
                try:
                    shutil.rmtree(category_path)
                    category_path.parent.rmdir()
                except OSError:
                    pass
            if manifest_stage_dir is not None and manifest_stage_dir.exists():
                shutil.rmtree(manifest_stage_dir, ignore_errors=True)
        if temporary_version.exists():
            shutil.rmtree(temporary_version)
        try:
            work_root.rmdir()
        except OSError:
            pass


_PUBLISH_LOCK_TIMEOUT_SECONDS = 30.0
_publish_thread_locks: dict[str, threading.Lock] = {}
_publish_thread_locks_guard = threading.Lock()


@contextlib.contextmanager
def _requirement_publish_lock(requirement_root: Path):
    """Serialize publishers per requirement across threads and OS processes.

    The stable hidden lock file is intentionally retained: unlinking a lock file
    can split waiters across different file identities. OS handles release locks
    automatically when a process exits.
    """
    root = Path(requirement_root).resolve()
    root.parent.mkdir(parents=True, exist_ok=True)
    lock_digest = hashlib.sha256(
        os.path.normcase(str(root)).encode("utf-8")
    ).hexdigest()[:16]
    lock_path = root.parent / f".qa-publish-{lock_digest}.lock"
    _require(not lock_path.is_symlink(), "需求发布锁文件不能是符号链接")
    lock_key = os.path.normcase(str(root))
    with _publish_thread_locks_guard:
        thread_lock = _publish_thread_locks.setdefault(lock_key, threading.Lock())
    if not thread_lock.acquire(timeout=_PUBLISH_LOCK_TIMEOUT_SECONDS):
        raise ManifestError("等待需求发布锁超时；当前没有提交版本，请稍后重新检查")

    lock_file = None
    try:
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(str(lock_path), flags, 0o600)
        lock_file = os.fdopen(descriptor, "r+b", buffering=0)
        deadline = time.monotonic() + _PUBLISH_LOCK_TIMEOUT_SECONDS
        while True:
            lock_file.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                contention = exc.errno in {
                    errno.EACCES,
                    errno.EAGAIN,
                    errno.EDEADLK,
                    errno.EWOULDBLOCK,
                } or getattr(exc, "winerror", None) in {33, 36}
                if not contention:
                    raise ManifestError(f"无法获取需求发布锁：{lock_path}") from exc
                if time.monotonic() >= deadline:
                    raise ManifestError(
                        f"等待需求发布锁超时：{lock_path}；当前没有提交版本，请稍后重新检查"
                    ) from exc
                time.sleep(0.05)

        if os.fstat(lock_file.fileno()).st_size == 0:
            lock_file.seek(0)
            lock_file.write(bytes([0]))
            lock_file.flush()
        yield
    finally:
        try:
            if lock_file is not None:
                lock_file.close()
        finally:
            thread_lock.release()


def _render_bug_receipt(requirement: dict, receipt: dict) -> tuple[str, str, dict]:
    """Validate a confirmed createBug success and render its immutable receipt."""
    _require(isinstance(receipt, dict), "Bug 回执输入必须为 JSON 对象")
    _require(
        receipt.get("creation_status") == "success",
        "仅 creation_status=success 可以生成正式 Bug 回执；失败或未知结果禁止归档",
    )
    raw_bug_id = receipt.get("bug_id")
    _require(
        (isinstance(raw_bug_id, str) or isinstance(raw_bug_id, int))
        and not isinstance(raw_bug_id, bool)
        and re.fullmatch(r"\d+", str(raw_bug_id)) is not None,
        "bug_id 必须为数字字符串或整数",
    )
    bug_id = str(raw_bug_id)
    title = _nonempty(receipt.get("title"), "receipt.title")
    content = _nonempty(receipt.get("content"), "receipt.content")
    assigned_to = _nonempty(receipt.get("assigned_to"), "receipt.assigned_to")
    assignee_name = receipt.get("assignee_name")
    if assignee_name is not None:
        assignee_name = _nonempty(assignee_name, "receipt.assignee_name")
    submitted_at = _nonempty(receipt.get("submitted_at"), "receipt.submitted_at")
    try:
        submitted = datetime.fromisoformat(submitted_at)
    except ValueError as exc:
        raise ManifestError("submitted_at 必须为有效 ISO 8601 时间") from exc
    _require(
        submitted.tzinfo is not None and submitted.utcoffset() == timedelta(hours=8),
        "submitted_at 必须保留北京时间 +08:00 时区偏移",
    )
    evidence = receipt.get("evidence")
    _require(
        isinstance(evidence, list)
        and bool(evidence)
        and all(isinstance(item, str) and item.strip() for item in evidence),
        "evidence 必须为至少包含一项的非空字符串数组",
    )
    pri = _nonempty(str(receipt.get("pri", "")), "receipt.pri")
    severity = _nonempty(str(receipt.get("severity", "")), "receipt.severity")
    env = _nonempty(receipt.get("env"), "receipt.env")
    bug_type = _nonempty(receipt.get("type"), "receipt.type")
    requirement_id = _nonempty(requirement.get("id"), "requirement.id")
    requirement_name = _nonempty(requirement.get("name"), "requirement.name")

    lines = [
        f"# BUG-{bug_id}｜{title}",
        "",
        "## 提交信息",
        f"- 禅道 Bug ID：{bug_id}",
        f"- 关联需求：{requirement_id}｜{requirement_name}",
        f"- 指派人员：{assignee_name + '（' + assigned_to + '）' if assignee_name else assigned_to}",
        f"- 优先级：{pri}",
        f"- 严重程度：{severity}",
        f"- 环境：{env}",
        f"- Bug 类型：{bug_type}",
        f"- 提交时间：{submitted.isoformat(timespec='seconds')}",
        "- 创建结果：成功（已收到禅道 Bug ID）",
        "",
        "## 最终提交正文",
        content,
        "",
        "## 缺陷证据",
    ]
    lines.extend(f"- {item.strip()}" for item in evidence)
    if receipt.get("code_locator"):
        lines.extend(["", "## 代码定位", _nonempty(receipt["code_locator"], "receipt.code_locator")])
    if receipt.get("requirement_basis"):
        lines.extend([
            "",
            "## 需求预期依据",
            _nonempty(receipt["requirement_basis"], "receipt.requirement_basis"),
        ])
    markdown = "\n".join(lines) + "\n"
    return (
        bug_id,
        markdown,
        {
            "bug_id": bug_id,
            "title": title,
            "assigned_to": assigned_to,
            "submitted_at": submitted.isoformat(timespec="seconds"),
        },
    )


def register_bug_receipt(requirement_root: Path, version_id: str, receipt: dict) -> dict:
    """Append one successful Bug receipt to the latest version's Manifest."""
    root = Path(requirement_root)
    with _requirement_publish_lock(root):
        records = _read_history(root)
        _require(bool(records), "需求没有正式版本，不能归档 Bug 回执")
        _require_writable_requirement_root(root)
        latest = records[-1]
        _require(
            version_id == latest["version_id"],
            f"只能向当前最新版本归档；当前最新版本为 {latest['version_id']}",
        )
        verify_history_artifact_files(root, records)
        verify_history_case_snapshots(root, records)

        current = latest["manifest"]
        bug_id, markdown, summary = _render_bug_receipt(current["requirement"], receipt)
        role = f"bug-submission-{bug_id}"
        relative_path = f"analysis/{version_id}/bug-submissions/BUG-{bug_id}.md"
        target = root / Path(*_safe_relative_path(relative_path, "bug_receipt.path"))
        manifest_path = latest["manifest_path"]

        _require(not target.exists(), f"Bug 回执文件已存在，拒绝覆盖：{relative_path}")
        _require(
            not any(
                item["category"] == "test-impact-analysis" and item["role"] == role
                for item in current["artifacts"]
            ),
            f"Manifest 已登记该 Bug 回执，拒绝重复登记：{bug_id}",
        )

        payload = markdown.encode("utf-8")
        artifact = {
            "category": "test-impact-analysis",
            "role": role,
            "path": relative_path,
            "source_version": version_id,
            "change": "added",
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        updated = dict(current)
        updated["artifacts"] = sorted(
            [*current["artifacts"], artifact],
            key=lambda item: (item["category"], item["role"]),
        )
        validate_manifest(updated, current["requirement"]["id"])

        target.parent.mkdir(parents=True, exist_ok=True)
        receipt_tmp = None
        manifest_tmp = None
        receipt_committed = False
        manifest_committed = False
        try:
            fd, receipt_tmp_name = tempfile.mkstemp(
                prefix=f".BUG-{bug_id}.", suffix=".tmp", dir=str(target.parent)
            )
            receipt_tmp = Path(receipt_tmp_name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            fd, manifest_tmp_name = tempfile.mkstemp(
                prefix=".manifest.", suffix=".tmp", dir=str(manifest_path.parent)
            )
            manifest_tmp = Path(manifest_tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(updated, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())

            _require(
                not target.exists(),
                f"Bug 回执文件在写入期间已出现，拒绝覆盖：{relative_path}",
            )
            os.replace(receipt_tmp, target)
            receipt_committed = True
            os.replace(manifest_tmp, manifest_path)
            manifest_committed = True

            refreshed = _read_history(root)
            refreshed_latest = refreshed[-1]
            _require(
                refreshed_latest["version_id"] == version_id,
                "回执登记后最新版本发生变化",
            )
            _require(
                any(
                    item["category"] == artifact["category"]
                    and item["role"] == artifact["role"]
                    and item["path"] == artifact["path"]
                    and item["sha256"] == artifact["sha256"]
                    for item in refreshed_latest["manifest"]["artifacts"]
                ),
                "回执 Manifest 登记回读不一致",
            )
            verify_history_artifact_files(root, refreshed)
            return {
                "result": "BUG_RECEIPT_REGISTERED",
                "bug_id": bug_id,
                "version_id": version_id,
                "receipt_path": str(target),
                "manifest_path": str(manifest_path),
                "sha256": artifact["sha256"],
                "artifact_count": len(refreshed_latest["manifest"]["artifacts"]),
                "summary": summary,
            }
        except Exception as exc:
            if receipt_committed and not manifest_committed:
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
            if manifest_committed:
                raise ManifestError(
                    f"Bug 回执与 Manifest 已写入，但回读验签失败；请人工核查 {target} 和 {manifest_path}，不得自动重复登记：{exc}"
                ) from exc
            raise
        finally:
            for temporary in (receipt_tmp, manifest_tmp):
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass


def publish_version(
    requirement_root: Path,
    requirement_id: str,
    requirement_name: str,
    staged_artifacts: list[dict],
    delivery_status: str = "complete",
    case_changes: dict | None = None,
    lineage: dict | None = None,
    retire_artifacts=(),
    created_at: str | None = None,
    expected_base_version: str | None = None,
) -> dict:
    """Publish only if the caller's baseline is still current under the requirement lock."""
    with _requirement_publish_lock(requirement_root):
        return _publish_version_locked(
            requirement_root,
            requirement_id,
            requirement_name,
            staged_artifacts,
            delivery_status,
            case_changes,
            lineage,
            retire_artifacts,
            created_at,
            expected_base_version,
        )


def _json_output(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P1 case identity and Manifest history")
    sub = parser.add_subparsers(dest="command", required=True)
    ids_parser = sub.add_parser("ids", help="Generate unused permanent Case IDs")
    ids_parser.add_argument("requirement_root", type=Path)
    ids_parser.add_argument("requirement_id")
    ids_parser.add_argument("--count", type=int, default=1)
    ids_parser.add_argument(
        "--baseline-manifest",
        type=Path,
        help="Use the latest complete case_snapshot as the historical identity ledger",
    )

    name_parser = sub.add_parser(
        "directory-name", help="Build a safe requirement archive folder name"
    )
    name_parser.add_argument("requirement_id")
    name_parser.add_argument("requirement_name")

    inspect_parser = sub.add_parser("inspect", help="Inspect the latest formal baseline")
    inspect_parser.add_argument("requirement_root", type=Path)

    validate_parser = sub.add_parser(
        "validate", help="Validate history and latest artifact hashes"
    )
    validate_parser.add_argument("requirement_root", type=Path)

    publish_parser = sub.add_parser(
        "publish", help="Publish one immutable version from a temporary JSON spec"
    )
    publish_parser.add_argument("requirement_root", type=Path)
    publish_parser.add_argument("spec", type=Path)

    bug_receipt_parser = sub.add_parser(
        "register-bug-receipt",
        help="Register one confirmed successful ZenTao Bug receipt in the latest Manifest",
    )
    bug_receipt_parser.add_argument("requirement_root", type=Path)
    bug_receipt_parser.add_argument("version_id")
    bug_receipt_parser.add_argument("receipt_json", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "directory-name":
            _json_output({
                "result": "DIRECTORY_NAME_READY",
                "directory_name": requirement_directory_name(
                    args.requirement_id, args.requirement_name
                ),
                "module_name": module_directory_name(args.requirement_name),
                "archive_relative_path": requirement_archive_relative_path(
                    args.requirement_id, args.requirement_name
                ),
            })
            return 0
        if args.command == "register-bug-receipt":
            receipt = json.loads(args.receipt_json.read_text(encoding="utf-8-sig"))
            result = register_bug_receipt(args.requirement_root, args.version_id, receipt)
            _json_output(result)
            return 0
        if args.command == "publish":
            spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
            _require(isinstance(spec, dict), "发布 spec 必须为 JSON 对象")
            req = spec.get("requirement")
            _require(isinstance(req, dict), "发布 spec 缺少 requirement 对象")
            _require(
                "expected_base_version" in spec,
                "publish spec 必须显式声明 expected_base_version；首次版本填 null，增量版本填写 inspect 返回的 latest_version",
            )
            result = publish_version(
                args.requirement_root,
                req.get("id"),
                req.get("name"),
                spec.get("artifacts", []),
                spec.get("delivery_status", "complete"),
                spec.get("case_changes"),
                spec.get("lineage"),
                spec.get("retire_artifacts", []),
                spec.get("created_at"),
                spec["expected_base_version"],
            )
            data = result["manifest"]
            _json_output({
                "result": result["result"],
                "version_id": result["version_id"],
                "version_path": result["version_path"],
                "delivery_status": data["delivery_status"],
                "artifact_count": len(data["artifacts"]),
                "case_count": data["case_count"],
                "retired_case_count": data["retired_case_count"],
                "validation": data["validation"],
            })
            return 0
        if args.command == "ids":
            if args.baseline_manifest is not None:
                existing = historical_case_ids_from_manifest(
                    args.requirement_root, args.requirement_id, args.baseline_manifest
                )
            else:
                existing = historical_case_ids(args.requirement_root)
            _json_output({
                "result": "CASE_IDS_GENERATED",
                "requirement_id": args.requirement_id,
                "case_ids": generate_case_ids(
                    args.requirement_id, existing, args.count
                ),
            })
            return 0

        records = _read_history(args.requirement_root)
        if not records:
            _json_output({"result": "NO_HISTORY", "version_count": 0})
            return 0
        latest_record = records[-1]
        latest_manifest = latest_record["manifest"]
        if args.command == "validate":
            historical_file_count = verify_history_artifact_files(
                args.requirement_root, records
            )
            verify_history_case_snapshots(args.requirement_root, records)
            _json_output({
                "result": "MANIFEST_HISTORY_PASS",
                "version_count": len(records),
                "historical_artifact_file_count": historical_file_count,
                "latest_version": latest_record["version_id"],
                "artifact_count": len(latest_manifest["artifacts"]),
                "case_count": latest_manifest["case_count"],
                "retired_case_count": latest_manifest["retired_case_count"],
            })
        else:
            parsed_cache = verify_history_case_snapshots(args.requirement_root, records)
            latest = load_latest_manifest(
                args.requirement_root, verify_files=True, records=records
            )
            baseline = resolve_latest_case_baseline(
                args.requirement_root, latest_record=latest, parsed_cache=parsed_cache
            )
            _json_output({
                "result": "MANIFEST_BASELINE_READY",
                "version_count": len(records),
                "latest_version": latest["version_id"],
                "manifest_path": str(latest["manifest_path"]),
                "requirement": latest_manifest["requirement"],
                "case_count": latest_manifest["case_count"],
                "retired_case_count": latest_manifest["retired_case_count"],
                "markdown_path": (
                    str(baseline["markdown_path"])
                    if baseline and baseline["markdown_path"]
                    else None
                ),
            })
        return 0
    except (
        ManifestError,
        artifacts.ArtifactError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        _json_output({"result": "FAIL", "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())