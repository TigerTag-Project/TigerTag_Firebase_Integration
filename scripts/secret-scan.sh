#!/usr/bin/env bash
#
# secret-scan.sh — dependency-free guard for the PUBLIC integration surface.
#
# This repo is the sanitized public projection of the PRIVATE TigerTag_Firebase_Backend
# (source of truth). Its whole purpose is to be safe to publish. This scan blocks a commit
# whose staged content would leak anything from the "never-leak denylist":
#   - service-account JSON / PEM private keys / *.env with real values / key + credential files
#   - real secret Firestore field VALUES (privateKey, apiKey hash/salt, tokens)
# Documenting a concept with an OBVIOUS placeholder (ab12cd34…, XXXX, 0000…) stays allowed.
#
# Run automatically via .githooks/pre-commit. Manual run: bash scripts/secret-scan.sh
# Bypass (do NOT, unless you are certain a hit is a false positive): git commit --no-verify
#
# Bash 3.2 compatible (macOS default) — no mapfile, no associative arrays.
set -o pipefail

fail=0
note() { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }

# --- staged file list (added/copied/modified/renamed) ---
files=$(git diff --cached --name-only --diff-filter=ACMR)
[ -z "$files" ] && exit 0

# 1) Forbidden FILENAMES ------------------------------------------------------
while IFS= read -r f; do
  [ -z "$f" ] && continue
  case "$f" in
    *.pem|*.p12|*.p8|*-key.json|*credentials.json|*serviceAccount*|*service_account*|*service-account*)
      note "forbidden secret-bearing file staged: $f" ;;
  esac
  base=$(basename "$f")
  case "$base" in
    .env.example|.env.sample|.env.template) : ;;  # templates ok
    .env|.env.*) note "forbidden env file staged (only *.example templates may ship): $f" ;;
  esac
done <<EOF
$files
EOF

# 2) Forbidden CONTENT in staged additions -----------------------------------
# Only ADDED lines (git diff -U0, '+' prefix), so pre-existing lines don't re-trip.
added=$(git diff --cached -U0 --no-color | grep -E '^\+' | sed 's/^\+//')

scan() { # <regex> <message>
  if printf '%s\n' "$added" | grep -Eiq "$1"; then note "$2"; fi
}

scan 'BEGIN[ A-Z]*PRIVATE KEY'                          'PEM private key detected'
scan '"type"[[:space:]]*:[[:space:]]*"service_account"' 'service-account JSON detected'
scan '"private_key"[[:space:]]*:[[:space:]]*"[^"]+"'    'service-account private_key value detected'

# Sensitive key = long secret-looking value, excluding obvious placeholders.
susp=$(printf '%s\n' "$added" \
  | grep -Ei '(private[_-]?key|privatekey|client[_-]?secret|api[_-]?secret|refresh[_-]?token|access[_-]?token|password)"?[[:space:]]*[:=][[:space:]]*"?[A-Za-z0-9/+_-]{20,}')
if [ -n "$susp" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    if printf '%s' "$line" | grep -Eiq 'ab12cd34|9876543210fedcba|XXXX|xxxx|<[^>]+>|0000000000|1234567890|example|placeholder|your[_-]|changeme|redacted'; then
      continue
    fi
    note "possible real secret value: $(printf '%.80s' "$line")"
  done <<EOF
$susp
EOF
fi

if [ "$fail" -ne 0 ]; then
  printf '\n\033[31mSECRET SCAN FAILED\033[0m — the above would leak into the PUBLIC integration repo.\n'
  printf 'Remove the secret (keep only placeholders), or if this is a genuine false positive,\n'
  printf 'commit with --no-verify (and double-check first).\n\n'
  exit 1
fi
exit 0
