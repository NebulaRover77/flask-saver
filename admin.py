#!/usr/bin/env python3
# admin.py — simple CLI for redirector's SQLite events DB (no backfill)
import os, sys, json, csv, time, argparse, sqlite3
import sys, csv, datetime
from typing import Any, Dict, Iterable

DB_PATH = os.getenv("DB_PATH", "/data/events.db")

def connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=10.0)
    con.row_factory = sqlite3.Row
    return con

def row_to_obj(r: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": r["id"],
        "ts": r["ts"],
        "method": r["method"],
        "path": r["path"],
        "query": r["query"],
        "headers": json.loads(r["headers"] or "{}"),
        "body": r["body"],
        "client_ip": r["client_ip"],
    }

def print_tuples(rows: Iterable[sqlite3.Row]) -> None:
    for r in rows:
        print((r["id"], r["ts"], r["method"], r["path"], r["query"], r["client_ip"]))

# ---- subcommands ----

def cmd_list(args: argparse.Namespace) -> None:
    con = connect()
    params = []
    where = []
    if args.contains:
        where.append("(path LIKE ? OR headers LIKE ? OR client_ip LIKE ?)")
        like = f"%{args.contains}%"
        params += [like, like, like]
    if args.since:
        where.append("ts >= ?")
        params.append(args.since)
    if args.until:
        where.append("ts <= ?")
        params.append(args.until)
    sql = "SELECT id,ts,method,path,query,client_ip FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    if args.limit is not None and args.limit > 0:
        sql += " LIMIT ?"
        params.append(args.limit)
    rows = list(con.execute(sql, params))
    if args.json:
        out = [
            {
                "id": r["id"],
                "ts": r["ts"],
                "method": r["method"],
                "path": r["path"],
                "query": r["query"],
                "client_ip": r["client_ip"],
            }
            for r in rows
        ]
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print_tuples(rows)

def _expand_ids(tokens):
    import re
    out = []
    for t in tokens:
        if t == "latest":
            out.append("latest")
        else:
            m = re.match(r"^(\d+)-(\d+)$", t)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                step = 1 if a <= b else -1
                out.extend(list(range(a, b + step, step)))
            else:
                out.append(int(t))
    return out

def cmd_show(args: argparse.Namespace) -> None:
    con = connect()
    ids = _expand_ids(args.ids)

    # If it's exactly ["latest"], behave like before
    if len(ids) == 1 and ids[0] == "latest":
        row = con.execute(
            "SELECT id,ts,method,path,query,headers,body,client_ip "
            "FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            print(json.dumps({"error": "not-found", "id": "latest"}))
            sys.exit(1)
        print(json.dumps(row_to_obj(row), indent=2, ensure_ascii=False))
        return

    # Otherwise, fetch all requested numeric IDs
    numeric_ids = [i for i in ids if i != "latest"]
    if not numeric_ids:
        print(json.dumps({"error": "bad-args", "detail": "only 'latest' given"}))
        sys.exit(2)

    # keep order the user typed
    out = []
    for i in numeric_ids:
        row = con.execute(
            "SELECT id,ts,method,path,query,headers,body,client_ip FROM events WHERE id=?",
            (int(i),)
        ).fetchone()
        if row:
            out.append(row_to_obj(row))
        else:
            out.append({"error": "not-found", "id": i})

    print(json.dumps(out, indent=2, ensure_ascii=False))

def cmd_delete(args: argparse.Namespace) -> None:
    con = connect()
    cur = con.cursor()

    ids = _expand_ids(args.ids)

    # Special-case: rm latest
    if len(ids) == 1 and ids[0] == "latest":
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            "SELECT id,ts,method,path,query,headers,body,client_ip "
            "FROM events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            con.rollback()
            print(json.dumps({"error": "not-found", "id": "latest"}))
            return
        cur.execute("DELETE FROM events WHERE id=?", (row["id"],))
        con.commit()
        print(json.dumps({"deleted": row_to_obj(row)}, indent=2, ensure_ascii=False))
        return

    if any(x == "latest" for x in ids):
        print(json.dumps({"error":"bad-args","detail":"cannot mix 'latest' with numeric ids"}))
        sys.exit(2)

    # De-dup while preserving order
    seen = set()
    numeric_ids = [i for i in ids if not (i in seen or seen.add(i))]
    if not numeric_ids:
        print(json.dumps({"deleted": []}, indent=2, ensure_ascii=False))
        return

    placeholders = ",".join("?" * len(numeric_ids))

    # Atomic select+delete
    cur.execute("BEGIN IMMEDIATE")
    rows = list(cur.execute(
        f"SELECT id,ts,method,path,query,headers,body,client_ip "
        f"FROM events WHERE id IN ({placeholders}) ORDER BY id",
        numeric_ids
    ))
    if rows:
        cur.executemany("DELETE FROM events WHERE id=?", [(r["id"],) for r in rows])
    con.commit()

    print(json.dumps({"deleted": [row_to_obj(r) for r in rows]}, indent=2, ensure_ascii=False))

def cmd_export(args: argparse.Namespace) -> None:
    con = connect()
    params = []
    where = []
    if args.contains:
        where.append("(path LIKE ? OR headers LIKE ? OR client_ip LIKE ?)")
        like = f"%{args.contains}%"
        params += [like, like, like]
    if args.since:
        where.append("ts >= ?")
        params.append(args.since)
    if args.until:
        where.append("ts <= ?")
        params.append(args.until)
    sql = "SELECT id,ts,method,path,query,headers,body,client_ip FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    rows = list(con.execute(sql, params))
    csv_path = args.csv
    if csv_path == "-":
        out = sys.stdout
        need_close = False
    else:
        out = open(csv_path, "w", newline="")
        need_close = True

    w = csv.writer(out)
    w.writerow(["id","ts","method","path","query","headers","body","client_ip"])
    for r in rows:
        w.writerow([r["id"], r["ts"], r["method"], r["path"], r["query"], r["headers"], r["body"], r["client_ip"]])
    if need_close:
        out.close()
        print(f"Wrote {len(rows)} rows to {csv_path}")

def cmd_tail(args: argparse.Namespace) -> None:
    con = connect()
    last_id = con.execute("SELECT IFNULL(MAX(id),0) FROM events").fetchone()[0]
    print(f"[tail] starting at id>{last_id} (Ctrl+C to stop)")
    try:
        while True:
            rows = list(con.execute(
                "SELECT id,ts,method,path,query,client_ip FROM events WHERE id>? ORDER BY id ASC",
                (last_id,)
            ))
            if rows:
                print_tuples(rows)
                last_id = rows[-1]["id"]
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

def cmd_stats(args: argparse.Namespace) -> None:
    con = connect()
    col = args.by
    if col not in {"client_ip","method","path"}:
        print("stats --by must be one of: client_ip, method, path", file=sys.stderr)
        sys.exit(2)
    rows = con.execute(
        f"SELECT {col} AS key, COUNT(*) AS n FROM events GROUP BY {col} ORDER BY n DESC LIMIT ?",
        (args.limit,)
    )
    for r in rows:
        print(f"{r['n']:6d}  {r['key']}")

# ---- main ----

def main() -> None:
    p = argparse.ArgumentParser(description="Admin CLI for redirector events DB")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("ls", help="List recent events")
    p_list.add_argument(
        "--limit",
        type=int,
        default=None,   # None = unlimited when the flag is omitted
        help="Max rows. Omit for unlimited; supply a number to limit."
    )
    p_list.add_argument("--contains", help="Substring search in path/headers/client_ip")
    p_list.add_argument("--since", help="ISO time lower bound (e.g. 2025-11-09T00:00:00Z)")
    p_list.add_argument("--until", help="ISO time upper bound")
    p_list.add_argument("--json", action="store_true", help="Output JSON")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("cat", help="Show one or more events as JSON")
    p_show.add_argument("ids", nargs="+", help="'latest' or numeric id(s); ranges like 1-6 allowed")
    p_show.set_defaults(func=cmd_show)

    p_del = sub.add_parser("rm", help="Delete one or more events and print deleted rows")
    p_del.add_argument("ids", nargs="+", help="'latest' or numeric id(s); ranges like 1-6 allowed")
    p_del.set_defaults(func=cmd_delete)

    p_exp = sub.add_parser("export", help="Export rows to CSV")
    p_exp.add_argument("--csv", required=True, help='Path or "-" for stdout')
    p_exp.add_argument("--contains", help="Substring search in path/headers/client_ip")
    p_exp.add_argument("--since", help="ISO time lower bound")
    p_exp.add_argument("--until", help="ISO time upper bound")
    p_exp.set_defaults(func=cmd_export)

    p_tail = sub.add_parser("tail", help="Follow new inserts (prints tuple lines)")
    p_tail.add_argument("--interval", type=float, default=1.0, help="Poll seconds")
    p_tail.set_defaults(func=cmd_tail)

    p_stats = sub.add_parser("stats", help="Top-N counts")
    p_stats.add_argument("--by", default="client_ip", help="client_ip|method|path")
    p_stats.add_argument("--limit", type=int, default=20)
    p_stats.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
