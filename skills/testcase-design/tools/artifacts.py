"""Minimal, agent-neutral structural checks for P1 Markdown and source-first Oracle.

No business-rule inference, persistent case database, or platform dependencies.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


class ArtifactError(ValueError):
    """An artifact violates its deterministic format contract."""


ROOT = re.compile(r"^#\s+(\d+)\s*[-—｜:： ]\s*(\S.*)$")
GROUP = re.compile(r"^##\s+(.+?)\s*$")
CASE = re.compile(r"^###\s+(.+?)\s*$")
IDENTITY = re.compile(r"^<!-- qa_case_id: (QA-(\d+)-[0-9a-f]{10}) -->$")
META = re.compile(r"^-\s+\*\*(优先级|前置条件|测试数据)\*\*：(.+)$")
STEP = re.compile(r"^(\d+)\.\s+\*\*操作\*\*：(.+)$")
EXPECTED = re.compile(r"^\s+-\s+\*\*预期\*\*：(.+)$")
APPENDIX = re.compile(r"^## 附录(?:(?:：|:)\s*\S.*)?$")
HEADING = re.compile(r"^#{1,6}(?:\s|$)")
PRIORITIES = {"P0", "P1", "P2", "P3", "P4"}
STATES = {"confirmed", "inferred"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactError(message)


def _value(raw: str, at: int) -> str:
    value = raw.strip()
    _require(bool(value), f"第 {at} 行：内容不能为空")
    return value


def parse_markdown(text: str) -> dict:
    """Parse the documented canonical subset, preserving group/case/step order."""
    requirement: dict | None = None
    groups: list[dict] = []
    group: dict | None = None
    case: dict | None = None
    step: dict | None = None
    seen: set[str] = set()
    appendix = False

    for line_no, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if appendix:
            # Appendix is terminal: structured cases placed here must never vanish.
            _require(not (
                HEADING.match(line)
                or line.startswith("<!-- qa_case_id:")
                or META.fullmatch(line)
                or STEP.fullmatch(line)
                or EXPECTED.fullmatch(line)
            ), f"第 {line_no} 行：附录之后不得出现用例结构或新标题")
            continue
        if requirement is None:
            match = ROOT.fullmatch(line)
            _require(match is not None, f"第 {line_no} 行：首个非空行必须为 # <需求编号>｜<需求名称>")
            requirement = {"id": match[1], "name": _value(match[2], line_no)}
            continue
        if APPENDIX.fullmatch(line):
            appendix = True
            continue
        match = GROUP.fullmatch(line)
        if match:
            group = {"name": _value(match[1], line_no), "cases": []}
            groups.append(group)
            case, step = None, None
            continue
        match = CASE.fullmatch(line)
        if match:
            _require(group is not None, f"第 {line_no} 行：用例缺少业务分组")
            case = {
                "title": _value(match[1], line_no),
                "case_id": None,
                "priority": None,
                "precondition": None,
                "test_data": None,
                "steps": [],
            }
            group["cases"].append(case)
            step = None
            continue
        _require(case is not None, f"第 {line_no} 行：发现分组之外的非结构化内容")

        match = IDENTITY.fullmatch(line)
        if match:
            _require(case["case_id"] is None and not case["steps"], f"第 {line_no} 行：Case ID 重复或位置错误")
            _require(match[2] == requirement["id"], f"第 {line_no} 行：Case ID 需求编号不一致")
            _require(match[1] not in seen, f"第 {line_no} 行：Case ID 重复：{match[1]}")
            seen.add(match[1])
            case["case_id"] = match[1]
            continue
        _require(case["case_id"] is not None, f"第 {line_no} 行：缺少内部 Case ID（需紧跟标题）")
        match = META.fullmatch(line)
        if match:
            key = {"优先级": "priority", "前置条件": "precondition", "测试数据": "test_data"}[match[1]]
            _require(not case["steps"] and case[key] is None, f"第 {line_no} 行：{match[1]}重复或应放在步骤之前")
            case[key] = _value(match[2], line_no)
            if key == "priority":
                _require(case[key] in PRIORITIES, f"第 {line_no} 行：优先级须为 P0–P4")
            continue
        match = STEP.fullmatch(line)
        if match:
            index = int(match[1])
            _require(index == len(case["steps"]) + 1, f"第 {line_no} 行：操作步骤须从 1 连续编号")
            step = {"action": _value(match[2], line_no), "expected": []}
            case["steps"].append(step)
            continue
        match = EXPECTED.fullmatch(line)
        if match:
            _require(step is not None, f"第 {line_no} 行：预期没有对应操作步骤")
            step["expected"].append(_value(match[1], line_no))
            continue
        raise ArtifactError(f"第 {line_no} 行：未知结构，检查缩进、字段名或语法")

    _require(requirement is not None, "Markdown 缺少需求标题")
    _require(bool(groups), "至少需要一个实际业务分组")
    for g in groups:
        _require(bool(g["cases"]), f"业务分组「{g['name']}」为空")
        for c in g["cases"]:
            _require(bool(c["case_id"]), f"用例「{c['title']}」缺少内部 Case ID")
            _require(bool(c["priority"]), f"用例「{c['title']}」缺少优先级")
            _require(bool(c["steps"]), f"用例「{c['title']}」没有操作步骤")
            for i, s in enumerate(c["steps"], 1):
                _require(bool(s["expected"]), f"用例「{c['title']}」第 {i} 步没有预期结果")
    return {"requirement": requirement, "groups": groups}


def _nonempty_string(value: object, where: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), f"{where} 必须为非空字符串")
    return value.strip()


def _source_ids(value: object, known: set[str], where: str) -> None:
    _require(isinstance(value, list) and bool(value), f"{where}.source_ids 至少引用一条来源")
    _require(all(isinstance(x, str) and x in known for x in value), f"{where}.source_ids 存在未知来源")
    _require(len(value) == len(set(value)), f"{where}.source_ids 存在重复引用")


def validate_oracle(data: object) -> dict:
    """Validate shape and traceability, not semantic completeness/correctness."""
    _require(isinstance(data, dict), "Oracle 顶层必须是 JSON 对象")
    _require(data.get("schema_version") == "1", "Oracle schema_version 应为字符串 1")
    req = data.get("requirement")
    _require(isinstance(req, dict), "Oracle 缺少 requirement 对象")
    _nonempty_string(req.get("id"), "requirement.id")
    _nonempty_string(req.get("name"), "requirement.name")
    sources = data.get("sources")
    _require(isinstance(sources, list) and bool(sources), "Oracle 需要至少一条独立需求来源")
    known: set[str] = set()
    for idx, source in enumerate(sources, 1):
        at = f"sources[{idx}]"
        _require(isinstance(source, dict), f"{at} 应为对象")
        key = _nonempty_string(source.get("id"), at + ".id")
        _require(key not in known, f"{at}.id 重复")
        known.add(key)
        _nonempty_string(source.get("description"), at + ".description")
        _nonempty_string(source.get("locator"), at + ".locator")
    obligations = data.get("obligations")
    _require(isinstance(obligations, list) and bool(obligations), "Oracle 需要至少一条来源驱动的业务义务")
    obligation_ids: set[str] = set()
    for idx, item in enumerate(obligations, 1):
        at = f"obligations[{idx}]"
        _require(isinstance(item, dict), f"{at} 应为对象")
        key = _nonempty_string(item.get("id"), at + ".id")
        _require(key not in obligation_ids, f"{at}.id 重复")
        obligation_ids.add(key)
        _source_ids(item.get("source_ids"), known, at)
        _nonempty_string(item.get("rule"), at + ".rule")
        _nonempty_string(item.get("expected_outcome"), at + ".expected_outcome")
        _require(isinstance(item.get("certainty"), str) and item["certainty"] in STATES,
                 f"{at}.certainty 必须为 confirmed/inferred 字符串")
    questions = data.get("open_questions", [])
    _require(isinstance(questions, list), "open_questions 必须为数组")
    for idx, item in enumerate(questions, 1):
        at = f"open_questions[{idx}]"
        _require(isinstance(item, dict), f"{at} 应为对象")
        _nonempty_string(item.get("question"), at + ".question")
        _nonempty_string(item.get("impact"), at + ".impact")
        _source_ids(item.get("source_ids"), known, at)
    return {
        "requirement": req,
        "source_count": len(sources),
        "obligation_count": len(obligations),
        "open_question_count": len(questions),
    }


def check_pair(markdown: str, oracle: object) -> dict:
    cases = parse_markdown(markdown)
    report = validate_oracle(oracle)
    _require(cases["requirement"] == {
        "id": report["requirement"]["id"],
        "name": report["requirement"]["name"],
    }, "Markdown 与 Oracle 的需求编号/名称不一致")
    return {
        "requirement": cases["requirement"],
        "group_count": len(cases["groups"]),
        "case_count": sum(len(g["cases"]) for g in cases["groups"]),
        "step_count": sum(len(c["steps"]) for g in cases["groups"] for c in g["cases"]),
        "oracle_sources": report["source_count"],
        "oracle_obligations": report["obligation_count"],
        "open_questions": report["open_question_count"],
        "semantic_review": "NOT_AUTOMATED",
        "result": "STRUCTURE_PASS",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P1 Markdown/Oracle deterministic checks")
    parser.add_argument("markdown", type=Path)
    parser.add_argument("oracle", type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_pair(
            args.markdown.read_text(encoding="utf-8-sig"),
            json.loads(args.oracle.read_text(encoding="utf-8-sig")),
        )
    except (ArtifactError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        # ASCII escapes keep stdout machine-readable under Windows GBK and UTF-8.
        print(json.dumps({"result": "FAIL", "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
