#!/usr/bin/env bash
set -uo pipefail

OUT=corpus.txt
TMP="$(mktemp "${OUT}.tmp.XXXX")"
: > "$TMP"
printf '%s\n\n' "# CORPUS-V1" >> "$TMP"

count=0
# pre-check tools
command -v python3 >/dev/null 2>&1 || PY_OK=0 && PY_OK=1

git ls-files -z | while IFS= read -r -d '' f; do
  case "${f,,}" in
    *.py|*.md)
      rel="${f#./}"
      size=$(wc -c < "$f" 2>/dev/null || echo 0)
      if command -v sha256sum >/dev/null 2>&1; then
        sha=$(sha256sum -- "$f" | awk '{print $1}')
      elif command -v shasum >/dev/null 2>&1; then
        sha=$(shasum -a256 "$f" | awk '{print $1}')
      elif command -v python3 >/dev/null 2>&1; then
        sha=$(python3 - <<'PY' "$f"

        
import hashlib,sys
h=hashlib.sha256()
with open(sys.argv[1],"rb") as fh:
    for b in iter(lambda: fh.read(8192), b""):
        h.update(b)
print(h.hexdigest())
PY
"$f")
      else
        sha="unknown"
      fi

      esc=$(printf '%s' "$rel" | sed 's/"/\\"/g')
      {
        printf '%s\n' "===FILE_START==="
        printf '%s\n' "{\"path\":\"$esc\",\"size\":$size,\"sha256\":\"$sha\"}"
        printf '%s\n' "===CONTENT==="
        cat -- "$f"
        printf '\n%s\n\n' "===FILE_END==="
      } >> "$TMP" || { printf 'Error writing %s\n' "$f" >&2; continue; }
      printf '.' >&2
      count=$((count+1))
      ;;
  esac
done

printf '\nPacked %d files into %s\n' "$count" "$OUT" >> "$TMP"
mv "$TMP" "$OUT"
