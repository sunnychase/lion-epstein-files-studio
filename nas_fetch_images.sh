#!/bin/bash
# nas_fetch_images.sh -- the image-only Epstein releases onto the NAS (Drive 2) for OCR on the Spark (operator 2026-11-16 "Add to NAS"):
#   1 DOJ EFTA Data Set 9 (107 GB zip)   2 DOJ EFTA Data Set 10 (84 GB zip)   3 House Oversight first production 2025-09 (33,295 pages: 34,242 files, 79 GB)
#   4 the House 2025-11-12 production's IMAGES/ (23,124 jpeg, 25 GB) for the studio's page viewer
# One job after another under the fetch-queue flock (NAS RAM 7.7 GB); each job logs to Download Logs/; nothing is deleted; the 300 GB floor on Drive 2.
set -u; L="/srv/data/Download Logs"; B=/srv/data/Drive2/Epstein/images; D="https://archive.org/download"; ts(){ date "+%F %T"; }
exec 9>/srv/data/OrcaRouter/.fetch_queue.lock; echo "$(ts)  QUEUED (waiting for the fetch lock)" >> "$L/_epstein_images_fetch.log"; flock 9
floor(){ a=$(df --output=avail -BG /srv/data/Drive2 | tail -1 | tr -dc 0-9); [ "$a" -gt $(( $1 + 300 )) ] || { echo "$(ts)  STOP Drive2 free ${a}G < $1 + 300 floor" >> "$L/_epstein_images_fetch.log"; exit 1; }; }
mkdir -p "$B/efta-dataset-9" "$B/efta-dataset-10" "$B/house-first-production-2025-09" "$B/house-additional-2025-11-12-images"
echo "$(ts)  START queue: sets 9, 10; House first production; House additional images · Drive2 free $(df -h --output=avail /srv/data/Drive2 | tail -1 | tr -d ' ')" >> "$L/_epstein_images_fetch.log"
floor 110; [ -s "$B/efta-dataset-9/DataSet 9.zip" ] || curl -sL --retry 5 -C - -o "$B/efta-dataset-9/DataSet 9.zip" "$D/epstein_library_transparency_act_hr_4405_dataset9_202602/DataSet%209.zip"; echo "$(ts)  set 9 rc $? $(du -sh "$B/efta-dataset-9" | cut -f1)" >> "$L/_epstein_images_fetch.log"
echo "item epstein_library_transparency_act_hr_4405_dataset9_202602 (archive.org): DOJ EFTA Data Set 9, fetched $(date -Is)" > "$B/efta-dataset-9/SOURCE.txt"
floor 90; [ -s "$B/efta-dataset-10/DataSet 10.zip" ] || curl -sL --retry 5 -C - -o "$B/efta-dataset-10/DataSet 10.zip" "$D/epstein_library_transparency_act_hr_4405_dataset10_202605/DataSet%2010.zip"; echo "$(ts)  set 10 rc $? $(du -sh "$B/efta-dataset-10" | cut -f1)" >> "$L/_epstein_images_fetch.log"
echo "item epstein_library_transparency_act_hr_4405_dataset10_202605 (archive.org): DOJ EFTA Data Set 10, fetched $(date -Is)" > "$B/efta-dataset-10/SOURCE.txt"
# the two per-file items: the file list from the item's _files.xml, eight downloads at a time, resumable (existing files skipped)
perfile(){ item=$1; dst=$2; pat=$3
  curl -sL -o "$dst/files.xml" "$D/$item/${item}_files.xml"
  python3 - "$dst/files.xml" "$dst" "$pat" <<'PY'
import re, os, sys
x, dst, pat = sys.argv[1:4]
names = [n for n in re.findall(r'<file name="([^"]+)"', open(x).read()) if re.search(pat, n) and not os.path.exists(os.path.join(dst, n))]
for n in names: os.makedirs(os.path.dirname(os.path.join(dst, n)) or dst, exist_ok=True)
open(dst + "/todo.txt", "w").write("".join(n + "\n" for n in names)); print(len(names), "to fetch")
PY
  ( cd "$dst" && cat todo.txt | xargs -P 8 -d '\n' -I{} sh -c 'curl -sL --retry 5 -o "{}" "'"$D/$item"'/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "{}")"' )
  echo "item $item (archive.org), fetched $(date -Is), pattern $pat" > "$dst/SOURCE.txt"
}
floor 80; perfile doj-jeffrey-epstein-first-production-2025 "$B/house-first-production-2025-09" '\.(jpg|jpeg|png|tif|tiff|pdf|txt|dat|opt|csv|xlsx?)$'; echo "$(ts)  House first production: $(find "$B/house-first-production-2025-09" -type f | wc -l) files $(du -sh "$B/house-first-production-2025-09" | cut -f1)" >> "$L/_epstein_images_fetch.log"
floor 30; perfile oversight-committee-additional-epstein-files "$B/house-additional-2025-11-12-images" '^IMAGES/'; echo "$(ts)  House additional IMAGES: $(find "$B/house-additional-2025-11-12-images" -type f | wc -l) files $(du -sh "$B/house-additional-2025-11-12-images" | cut -f1)" >> "$L/_epstein_images_fetch.log"
echo "$(ts)  EPSTEIN IMAGES QUEUE COMPLETE · Drive2 free $(df -h --output=avail /srv/data/Drive2 | tail -1 | tr -d ' ')" >> "$L/_epstein_images_fetch.log"; touch /srv/data/OrcaRouter/.epstein_images.done
