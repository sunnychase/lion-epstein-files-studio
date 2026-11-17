#!/bin/bash
# fetch_images.sh -- the compressed page images of a set from this repository's GitHub releases, verified and unpacked beside its text.
#   ./fetch_images.sh house-additional-2025-11-12 data/ia-house-oversight-additional-20251112
# Each set is a release tagged images-<set> holding <set>-NN.zip parts (<= 1.5 GB each) and <set>-MANIFEST.txt (sha256 of each part).
# The originals (full-resolution scans) are on archive.org; SOURCE.txt in every data folder names the item.
set -eu
SET=${1:?set name}; DST=${2:?destination folder}; REPO=${REPO:-sunnychase/lion-epstein-files-studio}
U="https://github.com/$REPO/releases/download/images-$SET"; mkdir -p "$DST" "$DST/.packs"
curl -sfL -o "$DST/.packs/$SET-MANIFEST.txt" "$U/$SET-MANIFEST.txt"
while read -r sha name rest; do
  [ -s "$DST/.packs/$name" ] || curl -sfL --retry 5 -C - -o "$DST/.packs/$name" "$U/$name"
  echo "$sha  $DST/.packs/$name" | sha256sum -c --quiet - || { echo "checksum failed: $name"; exit 1; }
  unzip -qo "$DST/.packs/$name" -d "$DST"; echo "unpacked $name ($rest)"
done < "$DST/.packs/$SET-MANIFEST.txt"
echo "done: $SET under $DST/IMAGES — now: python3 tools/backfill_images.py --db efiles.db --item <item>"
