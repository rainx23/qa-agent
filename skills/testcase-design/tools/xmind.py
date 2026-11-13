"""XMind (content.json) export with on-disk readback for P1.

Uses only Python stdlib; the Markdown parser remains the single case-content source.
XMind topic IDs are ephemeral and NEVER the QA Case ID or platform identity.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import re
import sys
import zlib
from uuid import uuid4
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from artifacts import ArtifactError, _require, parse_markdown


# XMind native number markers (1..5) represent P0..P4 in that order.
PRIORITY_MARKERS = {f"P{number}": f"priority-{number + 1}" for number in range(5)}
MARKER_PRIORITIES = {marker: priority for priority, marker in PRIORITY_MARKERS.items()}
STEP_TITLE = re.compile(r"^([1-9]\d*)\. (.+)$")
INTERNAL_ID = re.compile(r"QA-\d+-[0-9a-f]{10}")


def _topic(title: str, attached: list[dict] | None = None, *, priority: str | None = None) -> dict:
    result = {"id": uuid4().hex, "class": "topic", "title": title}
    if attached:
        result["children"] = {"attached": attached}
    if priority is not None:
        result["markers"] = [{"markerId": PRIORITY_MARKERS[priority]}]
    return result


def _make_sheet(parsed: dict) -> dict:
    groups = []
    for group in parsed["groups"]:
        cases = []
        for case in group["cases"]:
            nodes = []
            if case["precondition"] is not None:
                nodes.append(_topic("前置条件：" + case["precondition"]))
            if case["test_data"] is not None:
                nodes.append(_topic("测试数据：" + case["test_data"]))
            for i, step in enumerate(case["steps"], 1):
                expected = [_topic("预期：" + item) for item in step["expected"]]
                nodes.append(_topic(f"{i}. {step['action']}", expected))
            cases.append(_topic(case["title"], nodes, priority=case["priority"]))
        groups.append(_topic(group["name"], cases))
    root = parsed["requirement"]
    return {
        "id": uuid4().hex, "class": "sheet", "title": "测试用例",
        "rootTopic": {
            **_topic(f"{root['id']}｜{root['name']}", groups),
            "structure": "org.xmind.ui.logic.right",
        },
    }


def _package(parsed: dict) -> bytes:
    content = json.dumps([_make_sheet(parsed)], ensure_ascii=False, separators=(",", ":"))
    metadata = {"creator": {"name": "QA Agent", "version": "1.0"}}
    # This is XMind's internal package manifest, not the requirement-level
    # output/<module>/<requirement>/versions/<version>/manifest.json.
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as bundle:
        bundle.writestr("content.json", content.encode("utf-8"))
        bundle.writestr("metadata.json", json.dumps(metadata).encode("utf-8"))
        bundle.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
    return output.getvalue()


def _read_topics(topic: object, ids: set[str], where: str) -> tuple[str, list, list[str]]:
    """Read actual ZIP JSON nodes, never the pre-write in-memory sheet."""
    _require(isinstance(topic, dict), f"{where}：topic 必须为对象")
    identifier = topic.get("id")
    _require(isinstance(identifier, str) and identifier != "" and identifier not in ids,
             f"{where}：topic ID 缺失或重复")
    ids.add(identifier)
    _require(topic.get("class") == "topic", f"{where}：topic class 错误")
    title = topic.get("title")
    _require(isinstance(title, str) and title != "", f"{where}：topic 标题缺失")
    _require(INTERNAL_ID.search(title) is None, f"{where}：内部 Case ID 不得出现在展示节点")
    markers = topic.get("markers", [])
    _require(isinstance(markers, list) and all(
        isinstance(item, dict) and isinstance(item.get("markerId"), str) for item in markers
    ), f"{where}：markers 格式错误")
    _require(len(markers) <= 1, f"{where}：不允许多余优先级标记")
    marker_ids = [item["markerId"] for item in markers]
    children = topic.get("children", {})
    _require(isinstance(children, dict), f"{where}：children 格式错误")
    _require(set(children) <= {"attached"}, f"{where}：存在非 attached 节点，可能遗漏用例")
    attached = children.get("attached", [])
    _require(isinstance(attached, list), f"{where}：attached 节点格式错误")
    _require(set(topic) <= {"id", "class", "title", "children", "markers", "structure"},
             f"{where}：存在未校验的额外 topic 属性")
    return title, attached, marker_ids


def _no_marker(markers: list[str], where: str) -> None:
    _require(not markers, f"{where}：非用例节点不应出现优先级标记")


def read_xmind(path: Path) -> dict:
    """Read and normalize the *actual saved* XMind ZIP, rejecting unknown branches."""
    try:
        with ZipFile(path, "r") as bundle:
            names = bundle.namelist()
            _require(len(names) == len(set(names)), "XMind ZIP 存在重复文件名")
            _require({"content.json", "metadata.json", "manifest.json"} <= set(names),
                     "XMind ZIP 缺少必要包文件")
            _require(all(name in {"content.json", "metadata.json", "manifest.json"} for name in names),
                     "XMind ZIP 存在未处理的文件")
            _require(bundle.testzip() is None, "XMind ZIP CRC 校验失败")
            sheets = json.loads(bundle.read("content.json").decode("utf-8-sig"))
            _require(isinstance(json.loads(bundle.read("metadata.json").decode("utf-8")), dict),
                     "XMind metadata.json 非法")
            _require(isinstance(json.loads(bundle.read("manifest.json").decode("utf-8")), dict),
                     "XMind 内部 manifest.json 非法")
    except (BadZipFile, zlib.error, KeyError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        raise ArtifactError(f"XMind 文件损坏或内容不是有效 ZIP/JSON：{exc}") from exc
    _require(isinstance(sheets, list) and len(sheets) == 1, "XMind 应只有一个 sheet")
    sheet = sheets[0]
    _require(isinstance(sheet, dict) and sheet.get("class") == "sheet"
             and isinstance(sheet.get("id"), str) and sheet["id"]
             and isinstance(sheet.get("title"), str) and sheet["title"],
             "XMind sheet 格式错误")
    _require(set(sheet) == {"id", "class", "title", "rootTopic"},
             "XMind sheet 包含未校验的额外分支")
    ids = {sheet["id"]}
    root, raw_groups, marks = _read_topics(sheet.get("rootTopic"), ids, "需求根节点")
    _no_marker(marks, "需求根节点")
    match = re.fullmatch(r"(\d+)｜(\S.*)", root)
    _require(match is not None, "XMind 需求根节点格式错误")
    requirement = {"id": match[1], "name": match[2]}
    groups: list[dict] = []
    for group_idx, raw_group in enumerate(raw_groups, 1):
        group_name, raw_cases, marks = _read_topics(raw_group, ids, f"分组{group_idx}")
        _no_marker(marks, f"分组{group_idx}")
        _require(bool(raw_cases), f"分组{group_idx}没有任何用例")
        cases = []
        for case_idx, raw_case in enumerate(raw_cases, 1):
            where = f"分组{group_idx}用例{case_idx}"
            title, raw_steps, marks = _read_topics(raw_case, ids, where)
            _require(len(marks) == 1 and marks[0] in MARKER_PRIORITIES,
                     f"{where}：缺少或存在未知优先级标记")
            case = {
                "title": title, "priority": MARKER_PRIORITIES[marks[0]],
                "precondition": None, "test_data": None, "steps": [],
            }
            step_started = False
            for node_idx, node in enumerate(raw_steps, 1):
                at = f"{where}节点{node_idx}"
                value, raw_expected, markers = _read_topics(node, ids, at)
                _no_marker(markers, at)
                if value.startswith("前置条件：") or value.startswith("测试数据："):
                    key = "precondition" if value.startswith("前置条件：") else "test_data"
                    prefix = "前置条件：" if key == "precondition" else "测试数据："
                    _require(not step_started and case[key] is None and len(value) > len(prefix)
                             and not raw_expected, f"{at}：{key}位置或内容非法")
                    case[key] = value[len(prefix):]
                    continue
                step_started = True
                step_match = STEP_TITLE.fullmatch(value)
                _require(step_match is not None and int(step_match[1]) == len(case["steps"]) + 1,
                         f"{at}：操作步骤格式或顺序错误")
                _require(bool(raw_expected), f"{at}：操作步骤缺少预期")
                expected = []
                for expected_idx, raw_item in enumerate(raw_expected, 1):
                    exp_where = f"{at}预期{expected_idx}"
                    expected_text, leaf, markers = _read_topics(raw_item, ids, exp_where)
                    _no_marker(markers, exp_where)
                    _require(expected_text.startswith("预期：") and len(expected_text) > 3
                             and not leaf, f"{exp_where}：预期节点格式错误")
                    expected.append(expected_text[3:])
                case["steps"].append({"action": step_match[2], "expected": expected})
            _require(bool(case["steps"]), f"{where}：用例没有步骤")
            cases.append(case)
        groups.append({"name": group_name, "cases": cases})
    _require(bool(groups), "XMind 没有业务分组")
    return {"requirement": requirement, "groups": groups}


def _display_projection(parsed: dict) -> dict:
    # Case IDs must NEVER enter the XMind; only compare user-visible content.
    return {
        "requirement": parsed["requirement"],
        "groups": [{"name": g["name"], "cases": [
            {key: value for key, value in case.items() if key != "case_id"}
            for case in g["cases"]
        ]} for g in parsed["groups"]],
    }


def verify_xmind(parsed: dict, path: Path) -> dict:
    actual = read_xmind(path)
    wanted = _display_projection(parsed)
    _require(actual == wanted, "XMind 文件实际回读内容与 Markdown 不一致（分组、优先级、步骤、预期或顺序）")
    return {
        "result": "XMIND_READBACK_PASS",
        "group_count": len(actual["groups"]),
        "case_count": sum(len(group["cases"]) for group in actual["groups"]),
        "step_count": sum(len(case["steps"]) for g in actual["groups"] for case in g["cases"]),
        "semantic_review": "NOT_AUTOMATED",
        "desktop_open_verified": False,
    }


def export_xmind(markdown: str, path: Path) -> dict:
    """Never overwrite an existing archive; validate saved bytes after writing."""
    parsed = parse_markdown(markdown)
    _require(path.suffix.lower() == ".xmind", "输出文件必须以 .xmind 结尾")
    _require(not path.exists(), "目标 XMind 文件已存在，不覆盖正式历史产物")
    payload = _package(parsed)
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with path.open("xb") as handle:
            created = True
            handle.write(payload)
        return verify_xmind(parsed, path)
    except Exception as exc:
        if created:
            # Covers partial writes, close failures and readback failures.
            # Never remove a file for which exclusive creation failed.
            path.unlink(missing_ok=True)
        elif isinstance(exc, FileExistsError):
            raise ArtifactError("目标 XMind 文件已存在，不覆盖正式历史产物") from exc
        raise


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description="XMind export/readback from authority Markdown")
    cli.add_argument("markdown", type=Path)
    cli.add_argument("xmind", type=Path)
    cli.add_argument("--verify", action="store_true", help="Only read back and compare existing XMind")
    args = cli.parse_args(argv)
    try:
        markdown = args.markdown.read_text(encoding="utf-8-sig")
        if args.verify:
            result = verify_xmind(parse_markdown(markdown), args.xmind)
        else:
            result = export_xmind(markdown, args.xmind)
    except (ArtifactError, OSError, ValueError) as exc:
        print(json.dumps({"result": "FAIL", "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
