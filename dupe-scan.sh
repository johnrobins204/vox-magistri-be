#!/usr/bin/env bash
set -euo pipefail

echo "Scanning git-tracked files for duplicates..."
echo

TMP="$(mktemp)"
git ls-files > "$TMP"

# Build normalized keys: parentfolder.filename
# Example: app/api/v1/session.py → api.session.py
awk -F/ '
{
    if (NF == 1) {
        # File at repo root
        key = "ROOT." $NF
    } else {
        parent = $(NF-1)
        file = $NF
        key = parent "." file
    }
    print key
}' "$TMP" | sort | uniq -d > "$TMP.dupes"

echo "Duplicate file names detected:"
echo "--------------------------------"
cat "$TMP.dupes"
echo

echo "Detailed duplicate report:"
echo "--------------------------------"

while read -r key; do
    echo
    echo "=== $key ==="

    # Extract filename from key
    filename=$(echo "$key" | awk -F. '{print $2}')

    # Find all matching files in repo
    grep "/$filename$" "$TMP" | while read -r path; do
        size=$(stat -c%s "$path" 2>/dev/null || echo "?")
        mod=$(git log -1 --format="%ci" -- "$path" 2>/dev/null || echo "no git history")
        echo "File: $path"
        echo "  Size: $size bytes"
        echo "  Last edit: $mod"
    done
done < "$TMP.dupes"

echo
echo "Done."
