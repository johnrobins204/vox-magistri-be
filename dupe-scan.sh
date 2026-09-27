#!/usr/bin/env bash
set -euo pipefail

echo "Scanning git-tracked files for duplicates..."
echo

# 1. List all git-tracked files
git ls-files > all_files.txt

# 2. Build normalized keys: parentFolder.fileName
#    Example: src/app/api/v1/session.py → v1.session.py
awk -F/ '
{
    if (NF == 1) {
        key = "ROOT." $NF
    } else {
        parent = $(NF-1)
        file = $NF
        key = parent "." file
    }
    print key
}' all_files.txt > keys.txt

# 3. Find duplicate keys
sort keys.txt | uniq -d > dupes.txt

echo "Duplicate file names detected:"
echo "--------------------------------"
cat dupes.txt
echo

echo "Detailed duplicate report:"
echo "--------------------------------"

# 4. For each duplicate key, show all matching files + metadata
while read -r key; do
    echo
    echo "=== $key ==="

    filename="${key#*.}"   # everything after the dot

    # Find all files ending with this filename
    grep "/$filename$" all_files.txt | while read -r path; do
        size=$(stat -c%s "$path")
        mod=$(git log -1 --format="%ci" -- "$path" 2>/dev/null || echo "no git history")
        echo "File: $path"
        echo "  Size: $size bytes"
        echo "  Last edit: $mod"
    done
done < dupes.txt

echo
echo "Done."
