"""Database connector: introspect any SQLAlchemy database, suggest joins and
import a table, a join or a read-only query as a dataset.

Credentials stay on this machine; the LLM never sees them.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd
import sqlglot
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

MAX_IMPORT_ROWS = 500_000


def make_engine(url: str) -> Engine:
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_pre_ping=True)


def dialect_of(url: str) -> str:
    u = url.lower()
    for d in ("postgresql", "postgres", "mysql", "mariadb", "sqlite", "mssql", "oracle", "duckdb"):
        if u.startswith(d):
            return {"postgresql": "postgres", "mariadb": "mysql", "mssql": "tsql"}.get(d, d)
    return "sqlite"


def describe_database(url: str) -> dict[str, Any]:
    eng = make_engine(url)
    insp = inspect(eng)
    tables = []
    with eng.connect() as con:
        for t in insp.get_table_names():
            cols = [{"name": c["name"], "type": str(c["type"]), "nullable": c.get("nullable", True)} for c in insp.get_columns(t)]
            pk = insp.get_pk_constraint(t).get("constrained_columns", [])
            fks = [{"columns": fk["constrained_columns"], "ref_table": fk["referred_table"], "ref_columns": fk["referred_columns"]}
                   for fk in insp.get_foreign_keys(t)]
            try:
                n = con.execute(text(f'SELECT COUNT(*) FROM "{t}"' if eng.dialect.name != "mysql" else f"SELECT COUNT(*) FROM `{t}`")).scalar()
            except Exception:
                n = None
            tables.append({"name": t, "columns": cols, "primary_key": pk, "foreign_keys": fks, "rows": n})
    return {"dialect": eng.dialect.name, "tables": tables}


def suggest_joins(db: dict, selected: list[str]) -> list[dict]:
    """Join suggestions from declared foreign keys, then from matching column names."""
    by_name = {t["name"]: t for t in db["tables"]}
    sel = [t for t in selected if t in by_name]
    out: list[dict] = []
    seen = set()
    for t in sel:
        for fk in by_name[t]["foreign_keys"]:
            if fk["ref_table"] in sel:
                key = (t, fk["ref_table"], tuple(fk["columns"]))
                if key not in seen:
                    seen.add(key)
                    out.append({"left": t, "right": fk["ref_table"], "left_on": fk["columns"][0], "right_on": fk["ref_columns"][0],
                                "how": "left", "confidence": 1.0, "reason": "declared foreign key"})
    for i, a in enumerate(sel):
        for b in sel[i + 1:]:
            if any((o["left"], o["right"]) in ((a, b), (b, a)) for o in out):
                continue
            ca = {c["name"].lower(): c["name"] for c in by_name[a]["columns"]}
            cb = {c["name"].lower(): c["name"] for c in by_name[b]["columns"]}
            cands = []
            for name in set(ca) & set(cb):
                if name.endswith("id") or name.endswith("_key") or name.endswith("code"):
                    cands.append((0.8, ca[name], cb[name]))
            sb = re.sub(r"s$", "", b.lower())
            if f"{sb}_id" in ca and "id" in cb:
                cands.append((0.7, ca[f"{sb}_id"], cb["id"]))
            sa = re.sub(r"s$", "", a.lower())
            if f"{sa}_id" in cb and "id" in ca:
                cands.append((0.7, ca["id"], cb[f"{sa}_id"]))
            if cands:
                conf, lo, ro = max(cands)
                out.append({"left": a, "right": b, "left_on": lo, "right_on": ro, "how": "left", "confidence": conf,
                            "reason": "matching column names"})
    return out


def _quote(name: str, dialect: str) -> str:
    return f"`{name}`" if dialect == "mysql" else f'"{name}"'


def build_join_sql(db: dict, base: str, joins: list[dict]) -> str:
    """SELECT with prefixed column names so joined columns never collide."""
    d = db["dialect"]
    by_name = {t["name"]: t for t in db["tables"]}
    tables = [base] + [j["right"] if j["left"] in ([base] + [x["right"] for x in joins]) else j["left"] for j in joins]
    alias = {t: f"t{i}" for i, t in enumerate(dict.fromkeys(tables))}
    select = []
    for t, a in alias.items():
        for c in by_name[t]["columns"]:
            col_alias = c["name"] if t == base else f"{t}_{c['name']}"
            select.append(f"{a}.{_quote(c['name'], d)} AS {_quote(col_alias, d)}")
    sql = f"SELECT {', '.join(select)} FROM {_quote(base, d)} {alias[base]}"
    joined = {base}
    for j in joins:
        left, right = j["left"], j["right"]
        lo, ro = j["left_on"], j["right_on"]
        if right in joined and left not in joined:
            left, right, lo, ro = right, left, ro, lo
        how = "LEFT" if j.get("how", "left") == "left" else "INNER"
        sql += f" {how} JOIN {_quote(right, d)} {alias[right]} ON {alias[left]}.{_quote(lo, d)} = {alias[right]}.{_quote(ro, d)}"
        joined.add(right)
    return sql


def check_read_only(sql: str, dialect: str) -> str | None:
    try:
        parsed = sqlglot.parse(sql, read=dialect if dialect != "sqlite" else "sqlite")
    except Exception as e:
        return f"SQL could not be parsed: {e}"
    if len(parsed) != 1 or parsed[0] is None:
        return "Only a single statement is allowed."
    stmt = parsed[0]
    if stmt.key not in ("select", "union", "with", "subquery") and not isinstance(stmt, sqlglot.exp.Select):
        return "Only read-only SELECT queries are allowed."
    for node in stmt.walk():
        if isinstance(node, (sqlglot.exp.Insert, sqlglot.exp.Update, sqlglot.exp.Delete, sqlglot.exp.Drop, sqlglot.exp.Create, sqlglot.exp.Alter)):
            return "Only read-only SELECT queries are allowed."
    return None


def run_query(url: str, sql: str, limit: int) -> pd.DataFrame:
    eng = make_engine(url)
    err = check_read_only(sql, dialect_of(url))
    if err:
        raise ValueError(err)
    limit = max(1, min(int(limit), MAX_IMPORT_ROWS))
    with eng.connect() as con:
        df = pd.read_sql(text(f"SELECT * FROM ({sql}) dm_q LIMIT {limit}") if eng.dialect.name not in ("mssql", "oracle")
                         else text(sql), con)
    return df.head(limit)


def table_sql(table: str, url: str) -> str:
    return f"SELECT * FROM {_quote(table, 'mysql' if dialect_of(url) == 'mysql' else 'x')}"
