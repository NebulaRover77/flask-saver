import os
import json
import sqlite3
import datetime

from flask import Flask, request, redirect, g
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)

# -----------------------------
# Config (via environment vars)
# -----------------------------
DB_PATH = os.getenv("DB_PATH", "/data/events.db")
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "1048576"))  # 1MB
MASK_HEADERS = (
    set(h.strip().lower() for h in os.getenv("MASK_HEADERS", "authorization").split(","))
    if os.getenv("MASK_HEADERS")
    else {"authorization"}
)

# Trust X-Forwarded-* from Caddy (1 hop)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# -----------------------------
# SQLite helpers
# -----------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                query TEXT,
                headers TEXT NOT NULL,
                body TEXT,
                client_ip TEXT
            )
            """
        )
        g.db.commit()
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db:
        db.close()

# -----------------------------
# Utilities
# -----------------------------
def masked_headers(hdrs: dict) -> dict:
    """Mask sensitive headers before storing."""
    out = {}
    for k, v in hdrs.items():
        out[k] = "***" if k.lower() in MASK_HEADERS else v
    return out

def client_ip_from_request() -> str:
    # ProxyFix already set request.remote_addr from X-Forwarded-For.
    return request.remote_addr or ""

# -----------------------------
# Endpoints
# -----------------------------
@app.get("/healthz")
def healthz():
    return "ok", 200

# Catch-all for GET/POST
@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def catch(path: str):
    db = get_db()

    raw_body = request.get_data(cache=True)[:MAX_BODY_BYTES]
    safe_body = raw_body.decode("utf-8", errors="replace")
    headers = masked_headers(dict(request.headers))

    ts = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    client_ip = client_ip_from_request()

    db.execute(
        "INSERT INTO events (ts, method, path, query, headers, body, client_ip) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            ts,
            request.method,
            f"/{path}",
            request.query_string.decode(errors="replace"),
            json.dumps(headers, ensure_ascii=False),
            safe_body,
            client_ip,
        ),
    )
    db.commit()
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

# -----------------------------
# Local dev entrypoint
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
