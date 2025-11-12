# redirector

A tiny Flask service that **records every HTTP request** (method, path, query, headers, body, and client IP) into a SQLite database and replies with a plain `ok`. Useful as a sink/endpoint for debugging webhooks, CDN/edge rules, and redirect chains.

---

## Features

* **Catch‑all endpoint**: `GET` and `POST` on any path.
* **SQLite storage** at `${DB_PATH}` (default `/data/events.db`).
* **Header masking** for sensitive keys (default: `authorization`).
* **Body size cap** via `MAX_BODY_BYTES` (default: 1 MiB).
* **Admin CLI** (`admin`) to list, show, delete, export, tail, and get stats.
* **Health check** at `/healthz`.
* **Proxy‑aware** via `ProxyFix` (trusts one hop of `X‑Forwarded‑*`).

---

## Quick start (Docker Compose)

> Requires Docker and an external bridge network named `shared` (create it once with `docker network create shared`).

```bash
# build and start
docker compose up -d --build

# check health
docker compose exec redirector curl -s http://localhost:8080/healthz

# send a sample request from host
curl -i http://localhost:8080/test?hello=world -d 'hi there'
```

`compose.yml` exposes port **8080** to other services on the `shared` network (useful behind a reverse proxy like Caddy). Persisted DB lives in the `redirector_data` volume.

---

## Configuration (env vars)

| Variable         | Default           | Notes                                                             |
| ---------------- | ----------------- | ----------------------------------------------------------------- |
| `DB_PATH`        | `/data/events.db` | SQLite file inside the container volume                           |
| `MAX_BODY_BYTES` | `1048576`         | Bytes to read from the request body                               |
| `MASK_HEADERS`   | `authorization`   | Comma‑separated, case‑insensitive header names to mask in storage |

Set these in Compose under `services.redirector.environment`.

---

## Admin CLI (`admin.py`)

The Dockerfile symlinks `admin` into the image path. With the provided alias, you can exec it inside the container.

```bash
# (optional) add local convenience alias
# alias ra='docker exec -it redirector admin'
```

### List

```bash
admin ls --limit 20
admin ls --contains X-Forwarded-For --since 2025-11-09T00:00:00Z --json
```

### Show events

```bash
admin cat latest
admin cat 42 40 35-38
```

### Delete

```bash
admin rm latest
admin rm 10 12-15
```

### Export CSV

```bash
admin export --csv events.csv --since 2025-11-10T00:00:00Z
```

### Tail inserts

```bash
admin tail --interval 0.5
```

### Top‑N stats

```bash
admin stats --by path --limit 50
admin stats --by client_ip
```

> All CLI commands operate transactionally where appropriate and print machine‑readable JSON for modified rows.

---

## HTTP behavior

* **`/healthz`** → `200 ok` (text/plain).
* **Catch‑all** `GET`/`POST` on any path → `200 ok`. The service will store:

  * ISO timestamp (UTC, seconds precision).
  * `method`, normalized `path`, raw query string.
  * Masked request headers (per `MASK_HEADERS`).
  * Request body up to `MAX_BODY_BYTES` (UTF‑8 decoded with replacement).
  * `client_ip` derived from `request.remote_addr` (after `ProxyFix`).

---

## Data model

```sql
CREATE TABLE IF NOT EXISTS events (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT    NOT NULL,
  method    TEXT    NOT NULL,
  path      TEXT    NOT NULL,
  query     TEXT,
  headers   TEXT    NOT NULL,  -- JSON
  body      TEXT,
  client_ip TEXT
);
```

Query examples (host has sqlite3):

```bash
docker compose exec redirector sqlite3 /data/events.db \
  "SELECT id, ts, method, path, client_ip FROM events ORDER BY id DESC LIMIT 5;"
```

---

## Maintenance scripts

### `fix_ips.py`

Backfills `client_ip` for rows where it’s non‑public (e.g., container/private ranges) using:

* first public IP in `X‑Forwarded‑For` (prefers when hop‑2 matches old IP), then
* `CloudFront-Viewer-Address` as fallback.

Dry‑run by default:

```bash
docker compose exec redirector ./fix_ips.py            # dry‑run
docker compose exec redirector ./fix_ips.py --apply    # writes changes (creates backup)
```

### `delete_event.sh`

One‑liner helper to delete an event (by id or `latest`) directly via sqlite. Prefer the `admin rm` command; keep this as a fallback.

### `update-dyn.sh`

Ops helper for Hurricane Electric dynamic DNS updates (IPv4/IPv6). Expects env at `/opt/he-dyndns/env` with `HE_HOSTNAME` and `HE_PASSWORD`. Optional; unrelated to the service runtime.

---

## Local development (without Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DB_PATH="$(pwd)/events.db" MAX_BODY_BYTES=1048576 MASK_HEADERS=authorization
python app.py  # serves on 0.0.0.0:8080
```

Run with Gunicorn like the container does:

```bash
gunicorn -b 0.0.0.0:8080 app:app
```

---

## Reverse proxy tips

* Trust **exactly one hop** of `X‑Forwarded-*`. If you have more, adjust `ProxyFix` or terminate TLS directly in front.
* In Compose, the service is only **exposed** on 8080 (not published). Your proxy must join the `shared` network and target `redirector:8080`.

---

## Troubleshooting

* `network shared not found` → `docker network create shared`.
* No events recorded → ensure your proxy routes to `redirector:8080` and that requests hit the container (check `admin tail`).
* Masking not applied → verify `MASK_HEADERS` env is comma‑separated and restart the service.
* Large payloads truncated → raise `MAX_BODY_BYTES`.
