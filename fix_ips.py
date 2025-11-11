#!/usr/bin/env python3
# fix_ips.py — backfill client_ip using headers for rows with non-public client_ip
import os, sys, json, argparse, sqlite3, ipaddress, shutil, time

DB_PATH = os.getenv("DB_PATH", "/data/events.db")

def is_public(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except Exception:
        return False

def parse_cva(val: str) -> str:
    a = (val or "").strip().strip('"').strip("'")
    if a.startswith("["):
        end = a.find("]")
        host = a[1:end] if end != -1 else a.strip("[]")
    else:
        host = a.rsplit(":", 1)[0] if (":" in a and a.count(":") == 1) else a
    return host.strip()

def candidate_from_headers(headers_json: str, old_ip: str):
    """Return (new_ip, reason) or (None, reason)."""
    try:
        hk = {k.lower(): v for k, v in json.loads(headers_json or "{}").items()}
    except Exception:
        return None, "bad-json"

    # 1) X-Forwarded-For: pick the first PUBLIC IP; prefer when hop-2 == old_ip
    xff = hk.get("x-forwarded-for", "")
    parts = [p.strip().strip('"').strip("'") for p in xff.split(",") if p.strip()]
    first_public = None
    for p in parts:
        if is_public(p):
            first_public = p
            break
    if first_public:
        if len(parts) >= 2 and old_ip and parts[1] == old_ip:
            return first_public, "xff-second-hop-match"
        return first_public, "xff-first-public"

    # 2) CloudFront-Viewer-Address as a fallback (strip port, handle IPv6)
    cva = hk.get("cloudfront-viewer-address")
    if cva:
        host = parse_cva(cva)
        if is_public(host):
            return host, "cloudfront-viewer-address"

    return None, "no-candidate"

def backup_db(path: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    bak = f"{path}.bak.{ts}"
    shutil.copy2(path, bak)
    return bak

def main():
    ap = argparse.ArgumentParser(description="Fix non-public client_ip values using headers")
    ap.add_argument("--apply", action="store_true", help="write changes (default is dry-run)")
    ap.add_argument("--only-ips", help="comma-separated list to limit (e.g. 172.20.0.1,172.21.0.1)")
    ap.add_argument("--limit", type=int, default=None, help="max rows to scan (omit for all)")
    args = ap.parse_args()

    only_set = None
    if args.only_ips:
        only_set = {ip.strip() for ip in args.only_ips.split(",") if ip.strip()}

    con = sqlite3.connect(DB_PATH, timeout=10.0)
    con.row_factory = sqlite3.Row
    rows = list(con.execute("SELECT id, client_ip, headers FROM events ORDER BY id ASC"))
    if args.limit is not None and args.limit > 0:
        rows = rows[:args.limit]

    changes = []
    for r in rows:
        old_ip = (r["client_ip"] or "").strip()
        if not old_ip:
            continue

        # Default: target ANY non-public IP (private, loopback, link-local, etc.)
        target = not is_public(old_ip)
        # If --only-ips provided, further restrict to that set
        if only_set is not None:
            target = target and (old_ip in only_set)
        if not target:
            continue

        new_ip, reason = candidate_from_headers(r["headers"], old_ip)
        if new_ip and new_ip != old_ip:
            changes.append((r["id"], old_ip, new_ip, reason))

    print(f"Candidates: {len(changes)}")
    for id_, old, new, reason in changes[:25]:
        print(f"  ID {id_:>5}: {old:>15} -> {new:<15}  ({reason})")

    if not args.apply:
        print("\n[dry-run] No changes written. Re-run with --apply to write updates.")
        return

    if not changes:
        print("Nothing to update.")
        return

    bak = backup_db(DB_PATH)
    print(f"Backup created: {bak}")

    cur = con.cursor()
    cur.execute("BEGIN")
    for id_, old, new, reason in changes:
        cur.execute("UPDATE events SET client_ip=? WHERE id=?", (new, id_))
    con.commit()
    print(f"Updated {len(changes)} rows.")

if __name__ == "__main__":
    main()
