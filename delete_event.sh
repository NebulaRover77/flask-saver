ve_rm() {
  local id="${1:-latest}"

  docker exec -i redirector-redirector-1 python - "$id" <<'PY'
import sqlite3, json, sys

id_arg = sys.argv[1] if len(sys.argv) > 1 else "latest"

con = sqlite3.connect('/data/events.db')
cur = con.cursor()

def row_to_obj(r):
    return {
        "id": r[0], "ts": r[1], "method": r[2], "path": r[3], "query": r[4],
        "headers": json.loads(r[5] or "{}"), "body": r[6], "client_ip": r[7]
    }

# 1) Look up the row we intend to delete
if id_arg == "latest":
    row = cur.execute(
        "SELECT id,ts,method,path,query,headers,body,client_ip "
        "FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
else:
    try:
        rid = int(id_arg)
    except ValueError:
        print(json.dumps({"error": "bad-id", "id": id_arg}))
        sys.exit(1)
    row = cur.execute(
        "SELECT id,ts,method,path,query,headers,body,client_ip "
        "FROM events WHERE id=?", (rid,)
    ).fetchone()

if not row:
    print(json.dumps({"error": "not-found", "id": id_arg}))
    sys.exit(0)

# 2) Delete by the row’s id
cur.execute("DELETE FROM events WHERE id=?", (row[0],))
con.commit()

# 3) Print the deleted row for confirmation
print(json.dumps({"deleted": row_to_obj(row)}, indent=2, ensure_ascii=False))
PY
