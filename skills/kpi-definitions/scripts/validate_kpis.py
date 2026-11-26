#!/usr/bin/env python3
"""Validate a KPI dictionary (YAML or JSON) and render it as a Markdown metric dictionary.

Checks every KPI for id, name, description, formula, unit, grain, owner and direction;
parses each formula and checks that it only uses declared inputs, other KPIs and known
functions; finds dependency cycles, divisions without a zero_division rule, unused inputs
and placeholder owners. YAML support is a safe subset (block maps, lists, scalars,
[flow, lists], quoted strings, comments, | and > blocks); nothing is executed.

Exit codes: 0 = valid, 1 = errors (or warnings with --strict), 2 = cannot read or parse.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

GRAINS = {"event", "order", "user", "customer", "session", "day", "week", "month", "quarter", "year"}
UNITS = {"count", "currency", "percent", "ratio", "seconds", "minutes", "hours", "days"}
DIRECTIONS = {"up", "down", "neutral"}
AGGREGATIONS = {"sum", "count", "count_distinct", "avg", "min", "max", "median"}
FUNCTIONS = {"sum", "count", "avg", "min", "max", "abs", "round", "coalesce", "nullif", "count_distinct"}
REQUIRED = ["id", "name", "description", "formula", "unit", "grain", "owner"]
ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER_OWNERS = {"tbd", "todo", "unknown", "n/a", "na", "none", "?", "-", "someone"}

TEMPLATE = """\
# KPI dictionary. Validate: python3 scripts/validate_kpis.py kpis.yaml
version: 1
inputs:
  - id: gross_revenue
    description: Sum of order totals including shipping, before refunds
    source: orders.csv (total), status in paid, shipped, delivered
    aggregation: sum
  - id: refunds
    description: Sum of refunded amounts by refund date
    source: refunds.csv (amount)
    aggregation: sum
  - id: orders
    description: Count of distinct paid orders
    source: orders.csv (order_id)
    aggregation: count_distinct
  - id: customers
    description: Count of distinct customers with at least one paid order
    source: orders.csv (customer_id)
    aggregation: count_distinct
  - id: repeat_customers
    description: Distinct customers with two or more paid orders in the period
    source: orders.csv (customer_id)
    aggregation: count_distinct

kpis:
  - id: net_revenue
    name: Net revenue
    description: Revenue kept after refunds, the headline sales number
    formula: gross_revenue - refunds
    unit: currency
    currency: BDT
    grain: month
    owner: Finance (Head of Finance)
    direction: up
  - id: aov
    name: Average order value
    description: Net revenue per paid order
    formula: net_revenue / orders
    unit: currency
    currency: BDT
    grain: month
    owner: Growth team
    direction: up
    zero_division: null
  - id: repeat_rate
    name: Repeat customer rate
    description: Share of customers in the period who ordered at least twice
    formula: repeat_customers / customers
    unit: percent
    grain: month
    owner: CRM lead
    direction: up
    zero_division: 0
    target: 0.3
"""


class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'" and (i == 0 or line[i - 1] in " :[,-"):
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


KEY_RE = re.compile(r"""^("[^"]*"|'[^']*'|[^\s"'#\-\[{][^:]*?|-[^\s:][^:]*?)\s*:(?:\s+(.*)|$)""")


def _scalar(s: str):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        inner = s[1:-1]
        return inner.replace("''", "'") if s[0] == "'" else inner.replace('\\"', '"').replace("\\n", "\n")
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(x) for x in inner.split(",")] if inner else []
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        out = {}
        for part in filter(None, (p.strip() for p in inner.split(","))):
            k, _, v = part.partition(":")
            out[_scalar(k)] = _scalar(v)
        return out
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", ""):
        return None
    if re.match(r"^[+-]?\d+$", s):
        return int(s)
    if re.match(r"^[+-]?(\d+\.\d*|\.\d+|\d+(\.\d*)?[eE][+-]?\d+)$", s):
        return float(s)
    return s


def parse_yaml(text: str):
    """Parse the YAML subset used by KPI files. Raises YamlError with a line number."""
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.strip() in ("---", "...") or not raw.strip() or raw.lstrip().startswith("#"):
            continue
        lead = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in lead:
            raise YamlError(f"line {n}: tabs are not allowed for indentation")
        content = _strip_comment(raw.strip())
        if content:
            lines.append([n, len(lead), content])
    if not lines:
        return None
    value, i = _block(lines, 0, lines[0][1])
    if i != len(lines):
        raise YamlError(f"line {lines[i][0]}: unexpected indentation")
    return value


def _is_item(content: str) -> bool:
    return content == "-" or content.startswith("- ")


def _block(lines, i, indent):
    if _is_item(lines[i][2]):
        return _seq(lines, i, indent)
    return _map(lines, i, indent)


def _map(lines, i, indent):
    out: dict = {}
    while i < len(lines) and lines[i][1] == indent and not _is_item(lines[i][2]):
        n, _, content = lines[i]
        m = KEY_RE.match(content)
        if not m:
            raise YamlError(f"line {n}: expected 'key: value', got {content!r}")
        key, rest = _scalar(m.group(1)), (m.group(2) or "").strip()
        if key in out:
            raise YamlError(f"line {n}: duplicate key {key!r}")
        i += 1
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            block = []
            while i < len(lines) and lines[i][1] > indent:
                block.append(lines[i][2])
                i += 1
            out[key] = (" " if rest.startswith(">") else "\n").join(block)
        elif rest:
            out[key] = _scalar(rest)
        elif i < len(lines) and (lines[i][1] > indent or (lines[i][1] == indent and _is_item(lines[i][2]))):
            out[key], i = _block(lines, i, lines[i][1])
        else:
            out[key] = None
    if i < len(lines) and lines[i][1] > indent:
        raise YamlError(f"line {lines[i][0]}: unexpected indentation")
    return out, i


def _seq(lines, i, indent):
    out: list = []
    while i < len(lines) and lines[i][1] == indent and _is_item(lines[i][2]):
        n, _, content = lines[i]
        rest = content[1:].strip()
        if not rest:
            i += 1
            if i < len(lines) and lines[i][1] > indent:
                value, i = _block(lines, i, lines[i][1])
            else:
                value = None
        elif KEY_RE.match(rest) and not rest.startswith(("'", '"')) or re.match(r"^(\"[^\"]*\"|'[^']*')\s*:", rest):
            lines[i] = [n, indent + len(content) - len(rest), rest]
            value, i = _map(lines, i, lines[i][1])
        else:
            value, i = _scalar(rest), i + 1
        out.append(value)
    return out, i


def load(path: str):
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    if path.lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
        return json.loads(text)
    return parse_yaml(text)


TOKEN_RE = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_][A-Za-z0-9_]*)|([-+*/%(),])|(\S))")


def parse_formula(formula: str) -> tuple[set, set, bool, str | None]:
    """Return (identifiers, functions, has_division, error)."""
    tokens = []
    for num, ident, op, bad in TOKEN_RE.findall(formula):
        if bad:
            return set(), set(), False, f"unexpected character {bad!r}"
        tokens.append(("num", num) if num else ("id", ident) if ident else ("op", op))
    idents, funcs = set(), set()
    state = {"pos": 0, "div": False}

    def peek():
        return tokens[state["pos"]] if state["pos"] < len(tokens) else ("end", "")

    def take():
        tok = peek()
        state["pos"] += 1
        return tok

    def expr():
        term()
        while peek() in (("op", "+"), ("op", "-")):
            take()
            term()

    def term():
        factor()
        while peek() in (("op", "*"), ("op", "/"), ("op", "%")):
            if take()[1] == "/":
                state["div"] = True
            factor()

    def factor():
        kind, val = take()
        if (kind, val) in (("op", "-"), ("op", "+")):
            factor()
        elif kind == "num":
            return
        elif kind == "id":
            if peek() == ("op", "("):
                take()
                funcs.add(val.lower())
                if peek() != ("op", ")"):
                    expr()
                    while peek() == ("op", ","):
                        take()
                        expr()
                if take() != ("op", ")"):
                    raise ValueError(f"missing ')' after {val}(")
            else:
                idents.add(val)
        elif (kind, val) == ("op", "("):
            expr()
            if take() != ("op", ")"):
                raise ValueError("missing ')'")
        else:
            raise ValueError(f"unexpected {val or 'end of formula'!r}")

    try:
        if not tokens:
            raise ValueError("formula is empty")
        expr()
        if state["pos"] != len(tokens):
            raise ValueError(f"unexpected {peek()[1]!r}")
    except ValueError as exc:
        return idents, funcs, state["div"], str(exc)
    return idents, funcs, state["div"], None


def validate(doc) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []

    def err(where, msg):
        errors.append({"where": where, "message": msg})

    def warn(where, msg):
        warnings.append({"where": where, "message": msg})

    if isinstance(doc, list):
        doc = {"kpis": doc}
    if not isinstance(doc, dict):
        return {
            "errors": [{"where": "file", "message": "expected a map with 'kpis' or a list of KPIs"}],
            "warnings": [],
        }
    inputs = doc.get("inputs") or []
    kpis = doc.get("kpis")
    if not isinstance(kpis, list) or not kpis:
        err("file", "'kpis' must be a non-empty list")
        kpis = []
    if not isinstance(inputs, list):
        err("file", "'inputs' must be a list")
        inputs = []
    input_ids: dict[str, dict] = {}
    for j, inp in enumerate(inputs):
        where = f"inputs[{j}]"
        if not isinstance(inp, dict) or not inp.get("id"):
            err(where, "each input needs an id")
            continue
        iid = str(inp["id"])
        where = f"input {iid}"
        if not ID_RE.match(iid):
            err(where, "id must be snake_case (a-z, 0-9, _), starting with a letter")
        if iid in input_ids:
            err(where, "duplicate input id")
        input_ids[iid] = inp
        if not inp.get("description"):
            warn(where, "add a description (what is counted, which rows are excluded)")
        if not inp.get("source"):
            warn(where, "add a source (file/table and column)")
        agg = inp.get("aggregation")
        if agg and str(agg) not in AGGREGATIONS:
            err(where, f"aggregation {agg!r} is not one of {sorted(AGGREGATIONS)}")
    kpi_ids: dict[str, dict] = {}
    deps: dict[str, set] = {}
    used_inputs: set = set()
    for j, k in enumerate(kpis):
        if not isinstance(k, dict):
            err(f"kpis[{j}]", "each KPI must be a map")
            continue
        kid = str(k.get("id") or f"kpis[{j}]")
        where = f"kpi {kid}"
        for field in REQUIRED:
            if k.get(field) in (None, ""):
                err(where, f"missing '{field}'")
        if k.get("id") is not None:
            if not ID_RE.match(kid):
                err(where, "id must be snake_case (a-z, 0-9, _), starting with a letter")
            if kid in kpi_ids or kid in input_ids:
                err(where, "duplicate id (ids must be unique across inputs and KPIs)")
            kpi_ids[kid] = k
        unit, grain, direction = k.get("unit"), k.get("grain"), k.get("direction")
        if unit is not None and str(unit) not in UNITS:
            err(where, f"unit {unit!r} is not one of {sorted(UNITS)}")
        if grain is not None and str(grain) not in GRAINS:
            err(where, f"grain {grain!r} is not one of {sorted(GRAINS)}")
        if direction is None:
            warn(where, "add direction (up, down or neutral) so dashboards colour changes correctly")
        elif str(direction) not in DIRECTIONS:
            err(where, f"direction {direction!r} is not one of {sorted(DIRECTIONS)}")
        owner = k.get("owner")
        if owner is not None and str(owner).strip().lower() in PLACEHOLDER_OWNERS:
            err(where, f"owner {owner!r} is a placeholder; name a person or team")
        desc = k.get("description")
        if isinstance(desc, str) and len(desc.strip()) < 15:
            warn(where, "description is very short; say what it measures and what is excluded")
        if unit == "currency" and not k.get("currency"):
            warn(where, "unit is currency: add a currency code (BDT, USD)")
        formula = k.get("formula")
        if formula in (None, ""):
            continue
        idents, funcs, has_div, problem = parse_formula(str(formula))
        if problem:
            err(where, f"formula does not parse: {problem}")
        for f in sorted(funcs - FUNCTIONS):
            err(where, f"unknown function {f}() in formula (allowed: {', '.join(sorted(FUNCTIONS))})")
        deps[kid] = idents
        if has_div and "zero_division" not in k:
            warn(where, "formula divides: add zero_division (null or 0) to say what happens when the denominator is 0")
        if unit in ("percent", "ratio") and not has_div:
            warn(where, f"unit is {unit} but the formula has no division")
    for kid, idents in deps.items():
        for name in sorted(idents):
            if name in input_ids:
                used_inputs.add(name)
            elif name not in kpi_ids:
                err(f"kpi {kid}", f"formula uses unknown name '{name}' (declare it in inputs or as a KPI)")
    for iid in sorted(set(input_ids) - used_inputs):
        warn(f"input {iid}", "declared but not used by any KPI")
    for cycle in _cycles({k: {d for d in v if d in kpi_ids} for k, v in deps.items()}):
        err(f"kpi {cycle[0]}", "circular definition: " + " -> ".join(cycle))
    for kid, k in kpi_ids.items():
        for d in deps.get(kid, set()):
            if d in kpi_ids and kpi_ids[d].get("grain") and k.get("grain"):
                order = ["event", "order", "session", "user", "customer", "day", "week", "month", "quarter", "year"]
                g1, g2 = str(k["grain"]), str(kpi_ids[d]["grain"])
                if g1 in order and g2 in order and order.index(g2) > order.index(g1):
                    warn(f"kpi {kid}", f"uses {d} which has a coarser grain ({g2} vs {g1})")
    return {"kpis": list(kpi_ids), "inputs": list(input_ids), "errors": errors, "warnings": warnings}


def _cycles(graph: dict) -> list[list[str]]:
    found, seen = [], set()

    def visit(node, path):
        if node in path:
            cyc = path[path.index(node) :] + [node]
            key = frozenset(cyc)
            if key not in seen:
                seen.add(key)
                found.append(cyc)
            return
        for nxt in sorted(graph.get(node, ())):
            visit(nxt, path + [node])

    for start in sorted(graph):
        visit(start, [])
    return found


def render_markdown(doc) -> str:
    if isinstance(doc, list):
        doc = {"kpis": doc}
    out = ["# Metric dictionary", "", "| KPI | Definition | Formula | Unit | Grain | Owner | Direction |"]
    out.append("| --- | --- | --- | --- | --- | --- | --- |")
    for k in doc.get("kpis") or []:
        if not isinstance(k, dict):
            continue
        unit = str(k.get("unit", ""))
        if k.get("currency"):
            unit += f" ({k['currency']})"
        cells = [
            f"**{k.get('name', k.get('id', ''))}** (`{k.get('id', '')}`)",
            str(k.get("description", "")).replace("|", "\\|").replace("\n", " "),
            f"`{k.get('formula', '')}`",
            unit,
            str(k.get("grain", "")),
            str(k.get("owner", "")),
            str(k.get("direction", "")),
        ]
        out.append("| " + " | ".join(cells) + " |")
    if doc.get("inputs"):
        out += ["", "## Inputs", "", "| Input | Description | Source | Aggregation |", "| --- | --- | --- | --- |"]
        for i in doc["inputs"]:
            if isinstance(i, dict):
                cells = [f"`{i.get('id', '')}`", str(i.get("description", "")), str(i.get("source", ""))]
                out.append("| " + " | ".join([*cells, str(i.get("aggregation", ""))]) + " |")
    return "\n".join(out) + "\n"


def render_report(path: str, result: dict) -> str:
    out = [f"# KPI check: {path}", ""]
    out.append(f"{len(result['kpis'])} KPI(s), {len(result['inputs'])} input(s): ")
    out[-1] += f"{len(result['errors'])} error(s), {len(result['warnings'])} warning(s)"
    for level in ("errors", "warnings"):
        if result[level]:
            out += ["", f"## {level.title()}", ""]
            out += [f"- {i['where']}: {i['message']}" for i in result[level]]
    if not result["errors"] and not result["warnings"]:
        out += ["", "All KPIs are complete and consistent."]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Validate a KPI dictionary (YAML/JSON): formula, owner, grain, unit.")
    p.add_argument("path", nargs="?", help="kpis.yaml or kpis.json")
    p.add_argument("--markdown", action="store_true", help="print the metric dictionary as Markdown (after checks)")
    p.add_argument("--template", action="store_true", help="print a starter kpis.yaml and exit")
    p.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    p.add_argument("--json", action="store_true", help="print JSON")
    args = p.parse_args(argv)
    if args.template:
        print(TEMPLATE, end="")
        return 0
    if not args.path:
        p.error("path is required (or use --template)")
    try:
        doc = load(args.path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = validate(doc)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(render_report(args.path, result), end="")
        if args.markdown:
            print()
            print(render_markdown(doc), end="")
    failed = result["errors"] or (args.strict and result["warnings"])
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
