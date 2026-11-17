"""依赖零的 P3 SQL 风格检查；不解析 SQL 方言或业务语义。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KEYWORDS = set("""
all and any array as asc at between by case cast cross current_date
current_time current_timestamp date desc distinct else end except exists
extract false fetch filter first following from full group having in inner
intersect interval is join last lateral left like limit natural not null
nulls offset on or order outer over partition preceding range recursive
right row rows select semi some table then time timestamp to true union
unnest unbounded using values when where window with
""".split())

ALIAS_STOP = set("""
all as cross except fetch full group having inner intersect join left
limit natural offset on order outer right semi where window union
""".split())

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


def mask_non_code(sql: str) -> str:
    """屏蔽字符串与注释；保留引用标识符边界和字符串结束位置供结构检查使用。"""
    out = list(sql)
    state = "code"
    quote = ""
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
            if c == "'":
                state = "string"
                out[i] = " "
                i += 1
                continue
            if c in ('"', chr(96)):
                state = "identifier"
                quote = c
                out[i] = c
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
        elif state == "string":
            if c == "\\" and i + 1 < len(sql):
                out[i] = " " if c != "\n" else "\n"
                out[i + 1] = " " if sql[i + 1] != "\n" else "\n"
                i += 2
                continue
            if c == "'":
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    out[i:i + 2] = [" ", " "]
                    i += 2
                    continue
                out[i] = "x"
                state = "code"
            else:
                out[i] = "\n" if c == "\n" else " "
        else:
            if c == quote:
                if i + 1 < len(sql) and sql[i + 1] == quote:
                    out[i:i + 2] = [quote, quote]
                    i += 2
                    continue
                out[i] = quote
                state = "code"
            else:
                out[i] = "\n" if c == "\n" else " "
        i += 1
    return "".join(out)

def depth_map(code: str) -> list[int]:
    depth = 0
    result: list[int] = []
    for char in code:
        if char == ")":
            depth = max(0, depth - 1)
        result.append(depth)
        if char == "(":
            depth += 1
    return result


def line_number(sql: str, pos: int) -> int:
    return sql.count("\n", 0, pos) + 1


def add(issues: list[tuple[int, str]], sql: str, pos: int, message: str) -> None:
    issues.append((line_number(sql, pos), message))


def check_header(sql: str, issues: list[tuple[int, str]]) -> None:
    header = "\n".join(sql.splitlines()[:40])
    required = {
        "author: Rainx": r"\bauthor\s*:\s*Rainx\b",
        "create time (+08:00)": r"\bcreate\s*time\s*:.*\+08:00",
        "description": r"\bdescription\s*:\s*\S",
        "database": r"\bdatabase\s*:\s*\S",
        "execution_engine": r"\bexecution_engine\s*:\s*\S",
        "sql_dialect": r"\bsql_dialect\s*:\s*\S",
    }
    for label, pattern in required.items():
        if not re.search(pattern, header, re.I):
            add(issues, sql, 0, "文件头缺少或未完整填写 " + label)


def check_keywords(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    for match in IDENT.finditer(code):
        token = match.group(0)
        if token.lower() in KEYWORDS and token != token.lower():
            add(issues, sql, match.start(), f"SQL 关键字应小写：{token}")


def check_commas(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    depths = depth_map(code)
    for pos, char in enumerate(code):
        if char != "," or depths[pos] != 0:
            continue
        line_start = code.rfind("\n", 0, pos) + 1
        if code[line_start:pos].strip():
            add(issues, sql, pos, "顶层逗号应放在下一行行首")


def check_ctes(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    # CTE 声明保持单行，查询体的 select 从下一行开始。
    pattern = re.compile(
        r"\bwith\s+(?:recursive\s+)?"
        r"([A-Za-z_][A-Za-z0-9_$]*)(?:\s*\([^)]*\))?\s+as\s*\("
        r"|,\s*([A-Za-z_][A-Za-z0-9_$]*)(?:\s*\([^)]*\))?\s+as\s*\(",
        re.I,
    )
    for match in pattern.finditer(code):
        name = match.group(1) or match.group(2)
        if not name.startswith("v_"):
            add(issues, sql, match.start(), f"CTE 名称必须使用 v_ 前缀：{name}")
        if "\n" in code[match.start():match.end()]:
            add(issues, sql, match.start(), f"CTE 声明必须在同一行（with v_name as ( / , v_name as (）：{name}")
        body_start = match.end()
        if not re.match(r"[ \t]*\r?\n[ \t]*select\b", code[body_start:], re.I):
            add(issues, sql, body_start - 1, f"CTE 查询体的 select 必须另起一行（as ( 后换行）：{name}")


def enclosing_parenthesis_map(code: str) -> list[int]:
    """返回每个位置当前最内层未闭合左括号的位置；字符串/注释已由调用方屏蔽。"""
    stack: list[int] = []
    result: list[int] = [-1] * len(code)
    for pos, char in enumerate(code):
        if char == ")" and stack:
            stack.pop()
        result[pos] = stack[-1] if stack else -1
        if char == "(":
            stack.append(pos)
    return result


def is_function_syntax_from(code: str, open_pos: int) -> bool:
    """识别函数参数语法中的 FROM；它不是查询块的关系来源。"""
    if open_pos < 0:
        return False
    previous = re.search(r"([A-Za-z_][A-Za-z0-9_$]*)\s*$", code[:open_pos])
    if not previous:
        return False
    name = previous.group(1).lower()
    # 普通标识符紧邻左括号时按函数调用处理；EXTRACT 是关键字，但其表达式语法也使用 FROM。
    return name not in KEYWORDS or name == "extract"


def check_table_aliases(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    pattern = re.compile(
        r"\b(?:from|join)\s+"
        r"((?:[A-Za-z_][A-Za-z0-9_$]*\s*\.\s*)*[A-Za-z_][A-Za-z0-9_$]*)"
        r"(?:\s+(?:as\s+)?([A-Za-z_][A-Za-z0-9_$]*))?",
        re.I,
    )
    depths = depth_map(code)
    enclosing_open = enclosing_parenthesis_map(code)
    select_positions: dict[int, list[int]] = {}
    for token in IDENT.finditer(code):
        if token.group(0).lower() == "select":
            select_positions.setdefault(depths[token.start()], []).append(token.start())

    for match in pattern.finditer(code):
        depth = depths[match.start()]
        # 先排除函数参数语法中的 FROM（EXTRACT/SUBSTRING/TRIM 等），不受同深度历史 SELECT 影响。
        if is_function_syntax_from(code, enclosing_open[match.start()]):
            continue
        # 其余 FROM/JOIN 必须属于此前已开启的同深度查询块。
        if not any(pos < match.start() for pos in select_positions.get(depth, [])):
            continue
        relation = match.group(1).replace(" ", "").lower()
        if relation in {"lateral", "unnest", "values"}:
            continue
        alias = match.group(2)
        after_relation = code[match.end(1):].lstrip()
        if after_relation.startswith("("):
            continue  # 表函数；其别名形态由人工复核
        if alias and alias.lower() not in ALIAS_STOP:
            if not re.fullmatch(r"t[0-9]+", alias):
                add(issues, sql, match.start(2), f"表别名应使用 t1/t2 等形式：{alias}")
        else:
            add(issues, sql, match.start(1), f"表或 CTE 缺少 t1/t2 等别名：{match.group(1)}")


def top_level_tokens(code: str, depths: list[int]) -> list[tuple[str, int, int]]:
    tokens = []
    for match in IDENT.finditer(code):
        if depths[match.start()] == 0:
            tokens.append((match.group(0).lower(), match.start(), match.end()))
    return tokens



def split_top_level_columns(
    code: str, start: int, end: int, depths: list[int], target_depth: int = 0
) -> list[tuple[int, int]]:
    cuts = [
        pos for pos in range(start, end)
        if code[pos] == "," and depths[pos] == target_depth
    ]
    result = []
    cursor = start
    for pos in cuts:
        result.append((cursor, pos))
        cursor = pos + 1
    result.append((cursor, end))
    return result

def check_final_selects(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    depths = depth_map(code)
    tokens = top_level_tokens(code, depths)
    selects = [(start, end) for word, start, end in tokens if word == "select"]
    if not selects:
        add(issues, sql, 0, "未识别到顶层 SELECT；请人工确认 SQL 结构")
        return

    for select_start, select_end in selects:
        projection_end = len(code)
        for word, start, end in tokens:
            if start <= select_end:
                continue
            if word in {"from", "union", "intersect", "except"}:
                projection_end = start
                break
        semicolon = next(
            (pos for pos in range(select_end, projection_end) if code[pos] == ";" and depths[pos] == 0),
            None,
        )
        if semicolon is not None:
            projection_end = semicolon

        columns = split_top_level_columns(code, select_end, projection_end, depths)
        for col_start, col_end in columns:
            code_positions = [pos for pos in range(col_start, col_end) if not code[pos].isspace()]
            if not code_positions:
                continue
            last_code = code_positions[-1]
            line_start = sql.rfind("\n", 0, last_code) + 1
            line_end = sql.find("\n", last_code)
            if line_end < 0:
                line_end = len(sql)
            line = sql[line_start:line_end]
            tail = line[last_code - line_start + 1:]
            if not re.match(r"\s*--.*[\u3400-\u9fff]", tail):
                add(issues, sql, last_code, "最终 SELECT 输出列缺少同一行中文行内注释")

            # 使用原始片段识别输出别名，以支持双引号引用标识符。
            expression = sql[col_start:last_code + 1]
            alias_match = re.search(
                r'\bas\s+(?:"((?:""|[^"])*)"|([A-Za-z_][A-Za-z0-9_$]*))\s*$',
                expression,
                re.I,
            )
            if alias_match:
                alias = alias_match.group(1) if alias_match.group(1) is not None else alias_match.group(2)
                alias = alias.replace('""', '"')
                if not re.fullmatch(r"[a-z][a-z0-9_]*", alias):
                    add(issues, sql, col_start + alias_match.start(), f"输出别名应为小写英文 snake_case：{alias}")
def check_select_star(code: str, sql: str, issues: list[tuple[int, str]]) -> None:
    """检查每个查询块的投影列，避免漏掉非首列 alias.*。"""
    depths = depth_map(code)
    tokens = [
        (match.group(0).lower(), match.start(), match.end(), depths[match.start()])
        for match in IDENT.finditer(code)
    ]
    for word, select_start, select_end, query_depth in tokens:
        if word != "select":
            continue

        projection_start = select_end
        modifier = re.match(r"\s*(?:(?:distinct|all)\b\s*)?", code[projection_start:], re.I)
        if modifier:
            projection_start += modifier.end()

        projection_end = len(code)
        for next_word, start, end, depth in tokens:
            if start <= select_end or depth != query_depth:
                continue
            if next_word in {"from", "union", "intersect", "except"}:
                projection_end = start
                break

        semicolon = next(
            (
                pos for pos in range(projection_start, projection_end)
                if code[pos] == ";" and depths[pos] == query_depth
            ),
            None,
        )
        if semicolon is not None:
            projection_end = semicolon

        columns = split_top_level_columns(
            code, projection_start, projection_end, depths, query_depth
        )
        for col_start, col_end in columns:
            expression = code[col_start:col_end].strip()
            if re.fullmatch(
                r'(?:(?:[A-Za-z_][A-Za-z0-9_$]*|"(?:[^"]|"")*")\s*\.\s*)?\*',
                expression,
            ):
                add(issues, sql, col_start, "默认禁止 SELECT * / alias.*")
def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: python -B skills/sql-design/tools/check_sql_style.py <草稿.sql>", file=sys.stderr)
        return 2
    try:
        path = Path(argv[1])
        sql = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print("P3_SQL_STYLE_UNAVAILABLE: " + str(exc), file=sys.stderr)
        return 2

    code = mask_non_code(sql)
    issues: list[tuple[int, str]] = []
    check_header(sql, issues)
    check_keywords(code, sql, issues)
    check_commas(code, sql, issues)
    check_ctes(code, sql, issues)
    check_table_aliases(code, sql, issues)
    check_select_star(code, sql, issues)
    check_final_selects(code, sql, issues)

    print(
        "P3_SQL_STYLE_SCOPE: 文件头、常见 SQL 关键字大小写、顶层逗号、同一查询层级内简单关系 FROM/JOIN 别名（跳过函数调用参数语法中的 FROM，如 EXTRACT/SUBSTRING/TRIM；不受同深度已结束 SELECT 影响）、"
        "支持列名列表的 v_ CTE 单行声明、as ( 后换行且下一行以 select 开始、任意投影列的 SELECT * / alias.*、顶层 SELECT 输出注释及显式 AS 别名（含双引号）；"
        "不解析方言、字段存在性、复杂表函数/子查询别名或业务语义。"
    )
    issues = sorted(set(issues))
    if issues:
        print(f"P3_SQL_STYLE_FAIL: {len(issues)} 项")
        for line, message in issues[:40]:
            print(f"  L{line}: {message}")
        if len(issues) > 40:
            print(f"  ... 其余 {len(issues) - 40} 项已省略；请按上面的规则修复后重新运行")
        return 1
    print("P3_SQL_STYLE_PASS: 已覆盖的确定性风格检查通过；未覆盖项仍须人工复核")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
