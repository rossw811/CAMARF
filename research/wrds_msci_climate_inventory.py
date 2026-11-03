"""
Read-only inventory of the MSCI climate / ESG libraries on WRDS (2026-11-03): what the account can actually read
before any integration design. Earlier inventories (docs/DATA_SOURCES_SURVEY.md, job 34 on 2026-10-20) found MSCI as
sample libraries only; Ross reports the climate transition data has now been added.

For every library whose name matches msci / clim / esg / carbon / trc: each table's columns and types, estimated row
count, readable (a 5-row SELECT succeeds or is denied), the min/max of its date-like columns, which identifier
columns it has (issuer id, ISIN, CUSIP, SEDOL, ticker, GVKEY, PERMNO) and 5 sample rows. Fetches no data set.

Run attended only (Duo; unattended logins can lock the account):
    C:\\Users\\RossW\\anaconda3\\envs\\trading\\python.exe research/wrds_msci_climate_inventory.py
Writes output/research/wrds_msci_climate_inventory_<date>.json and a readable .md next to it.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_wrds import _connect

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "research")
LIB_PATTERN = re.compile(r"msci|clim|esg|carbon|trc", re.I)
DATE_COL = re.compile(r"date|as_?of|_dt$|^dt|year|period", re.I)
ID_COL = re.compile(r"issuer|isin|cusip|sedol|ticker|gvkey|permno|figi|lei", re.I)


def _sql_ident(s: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", s):
        raise ValueError(f"unexpected identifier {s!r}")
    return s


def inventory_table(db, lib: str, table: str) -> dict:
    lib, table = _sql_ident(lib), _sql_ident(table)
    out = {"table": table}
    try:
        desc = db.describe_table(lib, table)
        out["columns"] = [{"name": n, "type": str(t)} for n, t in zip(desc["name"], desc["type"])]
    except Exception as e:   # noqa: BLE001 -- record and move on, this is an inventory
        out["columns_error"] = str(e)[:300]
        return out
    try:
        out["rows_est"] = int(db.get_row_count(lib, table))
    except Exception as e:   # noqa: BLE001
        out["rows_est_error"] = str(e)[:200]
    try:
        sample = db.raw_sql(f"select * from {lib}.{table} limit 5")
        out["readable"] = True
        out["sample"] = json.loads(sample.to_json(orient="records", date_format="iso", default_handler=str))
    except Exception as e:   # noqa: BLE001
        out["readable"] = False
        out["read_error"] = str(e)[:300]
        return out
    names = [c["name"] for c in out["columns"]]
    out["id_columns"] = [n for n in names if ID_COL.search(n)]
    ranges = {}
    for n in [n for n in names if DATE_COL.search(n)][:4]:
        try:
            r = db.raw_sql(f"select min({_sql_ident(n)}) as lo, max({_sql_ident(n)}) as hi from {lib}.{table}")
            ranges[n] = [str(r["lo"].iloc[0]), str(r["hi"].iloc[0])]
        except Exception as e:   # noqa: BLE001
            ranges[n] = f"ERROR: {str(e)[:150]}"
    out["date_ranges"] = ranges
    return out


def to_markdown(inv: dict) -> str:
    lines = [f"# WRDS MSCI / climate inventory ({inv['run_at']})", "",
             f"Matching libraries: {', '.join(inv['libraries']) or 'none'}", ""]
    for lib, tables in inv["tables"].items():
        lines.append(f"## {lib}")
        if isinstance(tables, str):
            lines += [tables, ""]
            continue
        for t in tables:
            status = "readable" if t.get("readable") else f"NOT readable ({t.get('read_error', t.get('columns_error', '?'))[:120]})"
            lines.append(f"- **{t['table']}**: {status}; rows ~{t.get('rows_est', '?')}; ids {t.get('id_columns', [])}; "
                         f"dates {t.get('date_ranges', {})}; {len(t.get('columns', []))} columns")
        lines.append("")
    return "\n".join(lines)


def main():
    db = _connect()
    try:
        libs = sorted(l for l in db.list_libraries() if LIB_PATTERN.search(l))
        print(f"{len(libs)} matching libraries: {libs}")
        inv = {"run_at": dt.datetime.now().isoformat(timespec="seconds"), "libraries": libs, "tables": {}}
        for lib in libs:
            try:
                tables = db.list_tables(library=lib)
            except Exception as e:   # noqa: BLE001
                inv["tables"][lib] = f"ERROR listing tables: {str(e)[:200]}"
                continue
            print(f"{lib}: {len(tables)} tables")
            inv["tables"][lib] = [inventory_table(db, lib, t) for t in tables]
    finally:
        db.close()
    stamp = dt.date.today().strftime("%Y%m%d")
    os.makedirs(OUT_DIR, exist_ok=True)
    base = os.path.join(OUT_DIR, f"wrds_msci_climate_inventory_{stamp}")
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(inv, f, indent=1, default=str)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(to_markdown(inv))
    print(f"wrote {base}.json and .md")


if __name__ == "__main__":
    main()
