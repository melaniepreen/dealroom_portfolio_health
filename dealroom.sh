#!/bin/zsh
# Lists the 10 highest-valued VC-backed companies founded since 2020.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  print -u2 "Missing .env in this folder. Copy your downloaded credentials file here as .env."
  exit 1
fi

set -a
source .env
set +a

if [[ -z "${DEALROOM_CLIENT_ID:-}" || -z "${DEALROOM_CLIENT_SECRET:-}" ]]; then
  print -u2 ".env must define DEALROOM_CLIENT_ID and DEALROOM_CLIENT_SECRET."
  exit 1
fi

UA="dealroom-portfolio-health/1.0"
CACHE=".dealroom-token"
URL="https://api.beta.dealroom.app/data/companies?sort=-latest_valuation&limit=10&include_total=true&filter=and(classification[in_any]:vc_backed,launch_date[gte]:2020)"

mint_token() {
  local raw code body
  raw=$(curl -sS -X POST "https://accounts.dealroom.co/oauth/token" \
    -H "Content-Type: application/json" \
    -H "User-Agent: $UA" \
    -d "{\"client_id\":\"${DEALROOM_CLIENT_ID}\",\"client_secret\":\"${DEALROOM_CLIENT_SECRET}\",\"audience\":\"https://api.beta.dealroom.app\",\"grant_type\":\"client_credentials\"}" \
    -w $'\n%{http_code}')
  code="${raw##*$'\n'}"
  body="${raw%$'\n'*}"
  if [[ "$code" != "200" ]]; then
    print -u2 "Could not fetch a token (HTTP ${code}). Check the key in the Dealroom dashboard."
    print -u2 "$body"
    exit 1
  fi
  python3 -c '
import json, sys, time
payload = json.loads(sys.argv[1])
token = payload.get("access_token")
expires_in = int(payload.get("expires_in") or 0)
if not token or expires_in <= 0:
    sys.stderr.write("Token response did not include access_token and expires_in.\n")
    sys.exit(1)
open(sys.argv[2], "w").write(f"{int(time.time()) + expires_in}\n{token}\n")
' "$body" "$CACHE"
}

load_token() {
  local now exp
  now=$(date +%s)
  if [[ -f $CACHE ]]; then
    exp=$(sed -n '1p' "$CACHE")
    if [[ "$exp" =~ '^[0-9]+$' ]] && (( exp > now + 60 )); then
      sed -n '2p' "$CACHE"
      return
    fi
  fi
  mint_token
  sed -n '2p' "$CACHE"
}

call_api() {
  local token="$1"
  curl -sS -g "$URL" \
    -H "Authorization: Bearer ${token}" \
    -H "X-Client-Id: ${DEALROOM_CLIENT_ID}" \
    -H "User-Agent: ${UA}" \
    -w $'\n%{http_code}'
}

token=$(load_token)
raw=$(call_api "$token")
code="${raw##*$'\n'}"
body="${raw%$'\n'*}"

if [[ "$code" == "401" ]]; then
  mint_token
  token=$(sed -n '2p' "$CACHE")
  raw=$(call_api "$token")
  code="${raw##*$'\n'}"
  body="${raw%$'\n'*}"
  if [[ "$code" == "401" ]]; then
    print -u2 "The key was rejected. Create a new key in the Dealroom dashboard and replace .env."
    exit 1
  fi
fi

if [[ "$code" != "200" ]]; then
  print -u2 "Request failed (HTTP ${code})."
  print -u2 "$body"
  exit 1
fi

printf '%s' "$body" | python3 -c '
import json, sys

payload = json.load(sys.stdin)
rows = payload.get("data")
if rows is None:
    rows = payload.get("items") or payload.get("results") or payload.get("companies")
if not isinstance(rows, list):
    sys.stderr.write("Response had no company list. Top-level keys: %s\n" % ", ".join(payload.keys()))
    sys.exit(1)

def country(row):
    value = row.get("hq_country")
    if isinstance(value, dict):
        return value.get("name") or value.get("value") or value.get("code") or ""
    if value:
        return str(value)
    for location in row.get("locations") or []:
        if location.get("role") == "hq":
            country_value = location.get("country") or {}
            if isinstance(country_value, dict):
                return country_value.get("name") or ""
            return "" if country_value is None else str(country_value)
    return ""

def launch_year(row):
    value = row.get("launch_year")
    if value is None:
        value = row.get("launch_date")
    if value is None:
        return ""
    text = str(value)
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else text

def valuation(row):
    value = row.get("latest_valuation")
    if not isinstance(value, dict):
        value = row.get("valuation")
    if isinstance(value, dict):
        amount = value.get("value")
        return "" if amount is None else amount
    return "" if value is None else value

headers = ("name", "hq_country", "launch_year", "latest_valuation.value")
table = []
for row in rows:
    amount = valuation(row)
    table.append((
        "" if row.get("name") is None else str(row.get("name")),
        country(row),
        launch_year(row),
        "" if amount == "" else str(amount),
    ))

widths = [len(h) for h in headers]
for record in table:
    for i, cell in enumerate(record):
        widths[i] = max(widths[i], len(cell))

def line(cells):
    return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

print(line(headers))
print(" | ".join("-" * widths[i] for i in range(len(headers))))
for record in table:
    print(line(record))
'
