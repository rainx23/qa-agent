"""Reconcile discovered objects against one fixed report table, not Markdown evidence."""
import argparse
import json
from pathlib import Path

HEADING = "### 覆盖对账"
HEADER = ["对象标识", "静态核查", "解析目标", "CHK/EV或理由"]
STATUSES = {"PASS", "FAIL", "UNKNOWN", "N/A", "OUT_OF_SCOPE"}


def valid_id(value):
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(ch in value for ch in "|\r\n"))


def unique_ids(value):
    return (isinstance(value, list) and bool(value)
            and all(valid_id(key) for key in value) and len(set(value)) == len(value))


def cells(line):
    if not line.startswith("|") or not line.endswith("|"):
        return []
    return [cell.strip() for cell in line[1:-1].split("|")]


def coverage_table(report):
    lines = report.splitlines()
    starts = [i for i, line in enumerate(lines) if line == HEADING]
    if len(starts) != 1:
        raise ValueError("expected exactly one coverage section")
    start = starts[0] + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("#")), len(lines))
    declaration, _, table = "\n".join(lines[start:end]).strip().partition("\n")
    if declaration not in ("覆盖完整性：COMPLETE", "覆盖完整性：PARTIAL"):
        raise ValueError("invalid coverage declaration")
    rows = table.strip("\n").splitlines()
    if len(rows) < 2 or cells(rows[0]) != HEADER or cells(rows[1]) != ["---"] * 4:
        raise ValueError("invalid coverage table header or separator")
    return declaration.split("：")[1], rows[2:]


def reconcile(candidates, report):
    if not isinstance(candidates, list):
        raise ValueError("candidate file must be a JSON array")
    errors, expected, observed = [], {}, {}
    for item in candidates:
        if (not isinstance(item, dict) or not valid_id(item.get("id"))
                or not isinstance(item.get("source"), str) or not item["source"].strip()):
            errors.append("candidate requires valid id and nonempty source")
            continue
        key = item["id"]
        if key in expected:
            errors.append(f"duplicate candidate: {key}")
        expected[key] = item
        kind = item.get("kind", "object")
        if kind not in ("object", "unresolved_scope", "resolved_scope"):
            errors.append(f"invalid candidate kind: {key}")
        if kind == "resolved_scope":
            if not unique_ids(item.get("resolved_to")):
                errors.append(f"invalid resolved targets: {key}")
        elif "resolved_to" in item:
            errors.append(f"unexpected resolved targets: {key}")
    for key, item in expected.items():
        targets = item.get("resolved_to")
        if item.get("kind") == "resolved_scope" and unique_ids(targets):
            if any(target == key or target not in expected or
                   expected[target].get("kind", "object") != "object" for target in targets):
                errors.append(f"resolved targets must be actual candidate objects: {key}")

    claimed, rows = coverage_table(report)
    for line in rows:
        row = cells(line)
        if len(row) != 4 or not valid_id(row[0]):
            errors.append(f"invalid coverage row: {line}")
            continue
        key, state, mapping, _ = row  # Evidence/reason is read by AI, not validated here.
        if key in observed:
            errors.append(f"duplicate report object: {key}")
        observed[key] = state
        if state not in STATUSES:
            errors.append(f"invalid status: {key}: {state}")
        item = expected.get(key, {})
        kind = item.get("kind", "object")
        if kind == "unresolved_scope" and state != "UNKNOWN":
            errors.append(f"unresolved scope must remain UNKNOWN: {key}")
        if kind == "resolved_scope":
            if state != "N/A":
                errors.append(f"resolved scope must be N/A: {key}")
            try:
                targets = json.loads(mapping)
            except ValueError:
                targets = None
            expected_targets = item.get("resolved_to")
            if (not unique_ids(targets) or not unique_ids(expected_targets)
                    or set(targets) != set(expected_targets)):
                errors.append(f"report mapping differs from resolved_to: {key}")
        elif mapping != "-":
            errors.append(f"unexpected report mapping: {key}")

    missing = sorted(expected.keys() - observed.keys())
    extra = sorted(observed.keys() - expected.keys())
    unknown = sorted(key for key, state in observed.items() if state == "UNKNOWN")
    if missing or extra:
        errors.append("candidate/report object mismatch")
    if claimed == "COMPLETE" and (not expected or unknown):
        errors.append("COMPLETE contradicts empty discovery or unknown objects")
    if claimed == "PARTIAL" and not unknown:
        errors.append("PARTIAL requires an UNKNOWN object or unresolved scope")
    return {"result": "INVALID" if errors else claimed, "candidate_count": len(expected),
            "report_count": len(observed), "missing": missing, "extra": extra,
            "unknown": unknown, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        result = reconcile(json.loads(args.candidates.read_text(encoding="utf-8-sig")),
                           args.report.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as exc:
        result = {"result": "INVALID", "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return int(result["result"] == "INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
