"""Read-only ZenTao and ACE payload previews from canonical testcase Markdown.

This module never calls an MCP server and never writes to a platform.
Internal Case IDs stay in compact local mappings, not visible platform content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from artifacts import ArtifactError, parse_markdown


class PlatformPayloadError(ValueError):
    """The canonical testcase source cannot be mapped safely to a platform."""


# Historical adapter mapping: P1 -> ZenTao pri=2 is confirmed by a live
# historical readback. The remaining values are retained as a preview-only
# candidate and must be checked against current platform evidence before writes.
ZENTAO_PRIORITY_CANDIDATE = {
    "P0": 1,
    "P1": 2,
    "P2": 3,
    "P3": 4,
    "P4": 5,
}


def _positive_story_id(value: object) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise PlatformPayloadError("ZENTAO_STORY_ID_INVALID")
    return int(value)


def _precondition(case: dict) -> str:
    parts = []
    if case.get("precondition"):
        # ZenTao already renders the field label; send only the condition text.
        parts.append(case["precondition"])
    if case.get("test_data"):
        # Keep an explicit label because test data shares the precondition field.
        parts.append("测试数据：" + case["test_data"])
    return "\n".join(parts)



def build_zentao_preview(markdown: str, story_id: object) -> dict:
    """Build one-case-per-call MCP requests; never dispatch them."""
    story = _positive_story_id(story_id)
    parsed = parse_markdown(markdown)
    requirement = parsed["requirement"]
    if str(requirement["id"]) != str(story):
        raise PlatformPayloadError("ZENTAO_STORY_ID_DOES_NOT_MATCH_MARKDOWN")

    entries = []
    for group in parsed["groups"]:
        for case in group["cases"]:
            priority = case["priority"]
            if priority not in ZENTAO_PRIORITY_CANDIDATE:
                raise PlatformPayloadError("ZENTAO_PRIORITY_UNSUPPORTED:" + str(priority))
            steps = []
            for index, step in enumerate(case["steps"], 1):
                expected = step.get("expected")
                if not isinstance(expected, list) or not expected:
                    raise PlatformPayloadError(
                        "ZENTAO_STEP_EXPECTED_MISSING:" + str(case["case_id"]) + ":" + str(index)
                    )
                steps.append({
                    "stepNumber": index,
                    "stepDesc": step["action"],
                    "expectResult": "\n".join(expected),
                })
            request = {
                "story": story,
                "title": case["title"],
                "pri": ZENTAO_PRIORITY_CANDIDATE[priority],
                "type": "feature",
                "stepList": steps,
            }
            precondition = _precondition(case)
            if precondition:
                request["precondition"] = precondition
            entries.append({
                "case_id": case["case_id"],
                "group": group["name"],
                "request": request,
            })

    requests = [entry["request"] for entry in entries]
    request_bytes = json.dumps(
        requests, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    mapping_bytes = json.dumps(
        entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    source_bytes = markdown.lstrip("\ufeff").encode("utf-8")
    return {
        "status": "PREVIEW_ONLY",
        "platform": "zentao",
        "write_ready": False,
        "platform_sent": False,
        "story_id": str(story),
        "requirement": requirement,
        "case_count": len(entries),
        "transport_mode": "ONE_CASE_PER_MCP_CALL",
        "bulk_api_available": False,
        "priority_mapping_status": "HISTORICAL_CANDIDATE_NOT_FULLY_VERIFIED",
        "priority_mapping": dict(ZENTAO_PRIORITY_CANDIDATE),
        "source_markdown_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "payload_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "case_mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
        "requests": entries,
        "warnings": [
            "PREVIEW_ONLY_NO_PLATFORM_WRITE",
            "PRIORITY_MAPPING_REQUIRES_CURRENT_PLATFORM_VERIFICATION",
            "REMOTE_STEP_DETAIL_NOT_EXPOSED_BY_ZENTAO_MCP",
        ],
    }



ACE_PRIORITY_ICON_CANDIDATE = {
    "P0": "priority_1",
    "P1": "priority_2",
    "P2": "priority_3",
    "P3": "priority_4",
    "P4": "priority_5",
}


def _ace_positive_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PlatformPayloadError("ACE_" + field + "_INVALID")
    return value


def _ace_nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlatformPayloadError("ACE_" + field + "_REQUIRED")
    return value.strip()


def _ace_uid(story_id: str, identity: str) -> str:
    return str(uuid5(NAMESPACE_URL, "qa-agent:ace:" + story_id + ":" + identity))


def _ace_node(
    text: str,
    uid: str,
    *,
    tag: str | None = None,
    icon: str | None = None,
    children: tuple | list = (),
) -> dict:
    data = {"text": text, "uid": uid, "expand": True}
    if tag:
        data["tag"] = [{"text": tag}]
    if icon:
        data["icon"] = [icon]
    return {"data": data, "children": list(children)}


def build_ace_preview(markdown: str, target: object) -> dict:
    """Build one read-only ACE MindMap request from canonical Markdown.

    The request contains one requirement-root MindNode with the Markdown
    business groups and cases. Case IDs remain only in the local mapping;
    deterministic UUID5 values provide stable remote node identities.
    """
    if not isinstance(target, dict):
        raise PlatformPayloadError("ACE_TARGET_INVALID")

    parsed = parse_markdown(markdown)
    requirement = parsed["requirement"]

    story_id = str(_positive_story_id(target.get("story_id")))
    if story_id != str(requirement["id"]):
        raise PlatformPayloadError("ACE_STORY_ID_DOES_NOT_MATCH_MARKDOWN")

    story_name = _ace_nonempty_string(target.get("story_name"), "STORY_NAME")
    if story_name != requirement["name"]:
        raise PlatformPayloadError("ACE_STORY_NAME_DOES_NOT_MATCH_MARKDOWN")

    product_id = _ace_positive_integer(target.get("product_id"), "PRODUCT_ID")
    dir_id = _ace_positive_integer(target.get("dir_id"), "DIR_ID")
    project_id = _ace_nonempty_string(target.get("project_id"), "PROJECT_ID")
    project_name = _ace_nonempty_string(target.get("project_name"), "PROJECT_NAME")

    root_children = []
    case_mapping = []
    for group_index, group in enumerate(parsed["groups"], 1):
        group_children = []
        for case in group["cases"]:
            case_id = case["case_id"]
            priority = case["priority"]
            priority_icon = ACE_PRIORITY_ICON_CANDIDATE.get(priority)
            if priority_icon is None:
                raise PlatformPayloadError("ACE_PRIORITY_UNSUPPORTED:" + str(priority))

            case_children = []
            if case.get("precondition"):
                case_children.append(_ace_node(
                    "前置条件：" + case["precondition"],
                    _ace_uid(story_id, "precondition:" + case_id),
                    tag="前置条件",
                ))
            if case.get("test_data"):
                case_children.append(_ace_node(
                    "测试数据：" + case["test_data"],
                    _ace_uid(story_id, "test-data:" + case_id),
                    tag="测试数据",
                ))

            step_uids = []
            expected_uids = []
            for step_index, step in enumerate(case["steps"], 1):
                expected_nodes = []
                step_expected_uids = []
                for expected_index, expected in enumerate(step["expected"], 1):
                    expected_uid = _ace_uid(
                        story_id,
                        f"expected:{case_id}:{step_index}:{expected_index}",
                    )
                    step_expected_uids.append(expected_uid)
                    expected_nodes.append(_ace_node(
                        "预期：" + expected,
                        expected_uid,
                        tag="预期结果",
                    ))

                step_uid = _ace_uid(story_id, f"step:{case_id}:{step_index}")
                step_uids.append(step_uid)
                expected_uids.append(step_expected_uids)
                case_children.append(_ace_node(
                    f"步骤 {step_index}：" + step["action"],
                    step_uid,
                    tag="执行步骤",
                    children=expected_nodes,
                ))

            case_uid = _ace_uid(story_id, "case:" + case_id)
            group_children.append(_ace_node(
                case["title"],
                case_uid,
                tag="标题",
                icon=priority_icon,
                children=case_children,
            ))
            case_mapping.append({
                "case_id": case_id,
                "group": group["name"],
                "case_uid": case_uid,
                "priority": priority,
                "priority_icon": priority_icon,
                "step_uids": step_uids,
                "expected_uids": expected_uids,
            })

        root_children.append(_ace_node(
            group["name"],
            _ace_uid(story_id, f"group:{group_index}:{group['name']}"),
            children=group_children,
        ))

    root = _ace_node(
        requirement["name"],
        _ace_uid(story_id, "root"),
        children=root_children,
    )
    request = {
        "title": requirement["name"],
        "data": root,
        "product_id": product_id,
        "dir_id": dir_id,
        "project_id": project_id,
        "project_name": project_name,
        "story_id": story_id,
        "story_name": story_name,
    }

    source_bytes = markdown.lstrip("\ufeff").encode("utf-8")
    request_bytes = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    mapping_bytes = json.dumps(
        case_mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    def count_nodes(node: dict) -> int:
        return 1 + sum(count_nodes(child) for child in node["children"])

    return {
        "status": "PREVIEW_ONLY",
        "platform": "ace",
        "write_ready": False,
        "platform_sent": False,
        "transport_mode": "ONE_MINDMAP_PER_REQUIREMENT",
        "target": {
            "product_id": product_id,
            "dir_id": dir_id,
            "project_id": project_id,
            "project_name": project_name,
            "story_id": story_id,
            "story_name": story_name,
        },
        "group_count": len(parsed["groups"]),
        "case_count": len(case_mapping),
        "node_count": count_nodes(root),
        "priority_mapping_status": "CONFIGURED_MAPPING_IN_USE",
        "priority_mapping": dict(ACE_PRIORITY_ICON_CANDIDATE),
        "source_markdown_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "payload_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "case_mapping_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
        "request": request,
        "case_mapping": case_mapping,
        "warnings": [
            "PREVIEW_ONLY_NO_PLATFORM_WRITE",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only ZenTao import payload preview")
    parser.add_argument("--markdown", required=True, type=Path)
    parser.add_argument("--story-id", required=True)
    args = parser.parse_args(argv)
    try:
        markdown = args.markdown.read_text(encoding="utf-8-sig")
        result = build_zentao_preview(markdown, args.story_id)
    except (ArtifactError, PlatformPayloadError, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
