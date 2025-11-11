#!/usr/bin/env bash
set -euo pipefail

source /opt/he-dyndns/env

log(){ logger -t he-dyndns "$*"; echo "$*"; }

update_ip(){
  local ver="$1" ip url out curl_opts
  if [[ "$ver" == "4" ]]; then
    ip="$(curl -4 -fsS https://api.ipify.org)"
  else
    ip="$(curl -6 -fsS https://api64.ipify.org)"
  fi
  # Build URL
  url="https://dyn.dns.he.net/nic/update?hostname=${HE_HOSTNAME}&password=${HE_PASSWORD}&myip=${ip}"

  # NOTE: HE docs mention their dyn endpoint may present a self-signed cert.
  # If your curl fails on TLS, add:  curl_opts=(--insecure)  (or use http://)
  curl_opts=()
  out="$(curl -fsS "${curl_opts[@]}" "$url")" || { log "ERROR v$ver update failed"; exit 1; }

  # Typical responses: 'good <ip>' (updated) or 'nochg <ip>' (no change)
  log "v$ver: $out"
}

# IPv4 update
update_ip 4 || true

# IPv6 update (skip silently if host has no global v6)
if curl -6 -fsS https://api64.ipify.org >/dev/null 2>&1; then
  update_ip 6 || true
fi
