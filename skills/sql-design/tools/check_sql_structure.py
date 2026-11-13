"""只读检查未加引号的 v_ CTE 是否被跨语句误用。

不解析反引号等引用标识符，不等同于 SQL 方言、字段、语法或业务校验。
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

# CTE 之间逗号后可以没有空格；from/join 后的限定表名不是裸 CTE。
CTE = re.compile(r"(?:\bwith\s+|,\s*)(v_[A-Za-z_]\w*)\s+as\s*\(", re.I)
REF = re.compile(r"\b(?:from|join)\s+(v_[A-Za-z_]\w*)\b(?!\s*\.)", re.I)
QUERY = re.compile(r"\b(?:select|with)\b", re.I)
BLOCK = re.compile(r"(?m)^[ \t]*--[ \t]*(SQL-(?:[FV])?\d+)\b", re.I)

def mask_non_code(sql: str) -> str:
    out = list(sql)
    state = "code"
    i = 0
    while i < len(sql):
        c = sql[i]
        pair = sql[i:i + 2]
        if state == "code":
            if pair == "--":
                state = "line"
                out[i:i + 2] = [" ", " "]
                i += 2
                continue
            if pair == "/*":
                state = "block"
                out[i:i + 2] = [" ", " "]
                i += 2
                continue
            if c in ("'", '"', chr(96)):
                state = c
                out[i] = " "
                i += 1
                continue
        elif state == "line":
            if c == "\n":
                state = "code"
            else:
                out[i] = " "
        elif state == "block":
            if pair == "*/":
                out[i:i + 2] = [" ", " "]
                state = "code"
                i += 2
                continue
            if c != "\n":
                out[i] = " "
        else:
            if c == "\\" and i + 1 < len(sql):
                out[i:i + 2] = [" ", " "]
                i += 2
                continue
            if c == state:
                if i + 1 < len(sql) and sql[i + 1] == state:
                    out[i:i + 2] = [" ", " "]
                    i += 2
                    continue
                state = "code"
            out[i] = " " if c != "\n" else "\n"
        i += 1
    return "".join(out)


def find_scope_issues(sql: str) -> list[tuple[str, int, str]]:
    masked = mask_non_code(sql)
    prior_ctes: set[str] = set()
    issues: list[tuple[str, int, str]] = []
    boundaries = [0] + [i + 1 for i, c in enumerate(masked) if c == ";"] + [len(sql)]
    statement_number = 0
    for start, end in zip(boundaries, boundaries[1:]):
        part = masked[start:end]
        if not QUERY.search(part):
            continue
        statement_number += 1
        declared = {m.group(1).lower() for m in CTE.finditer(part)}
        ids = BLOCK.findall(sql[start:end])
        label = ids[-1] if ids else "statement " + str(statement_number)
        for match in REF.finditer(part):
            name = match.group(1).lower()
            if name in prior_ctes and name not in declared:
                line = sql.count("\n", 0, start + match.start(1)) + 1
                issues.append((label, line, name))
        prior_ctes |= declared
    return issues


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: python -B check_sql_structure.py <草稿.sql>", file=sys.stderr)
        return 2
    try:
        sql = Path(argv[1]).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print("P3_SQL_SCOPE_UNAVAILABLE: " + str(exc), file=sys.stderr)
        return 2
    issues = find_scope_issues(sql)
    if issues:
        print("P3_SQL_SCOPE_FAIL: " + str(len(issues)) + " 处跨语句 CTE 引用")
        for label, line, name in issues:
            print(f"  {label} L{line}: {name} 仅在之前的语句定义")
        return 1
    print("P3_SQL_SCOPE_PASS: 未发现未加引号的 v_ CTE 跨语句引用（非完整 SQL 语法/业务校验）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
