#!/usr/bin/env python3
# Created by Sunny Chase (https://github.com/sunnychase) in collaboration with Claude (Anthropic) · Lion Epstein Files Studio
"""backfill_images.py -- after the page images of a production item arrive (compressed packs or originals), point each page at its image
by Bates number: pages.image_path = the file under <source_dir>/IMAGES whose name is the page's Bates stamp.
  python3 tools/backfill_images.py --db efiles.db --item ia-house-oversight-additional-20251112
"""
import argparse, os, sqlite3

ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); ap.add_argument("--item", required=True); a = ap.parse_args()
db = sqlite3.connect(a.db, timeout=60)
sd = db.execute("SELECT source_dir FROM items WHERE id=?", (a.item,)).fetchone()
if not sd:
    raise SystemExit("no such item")
root = os.path.join(sd[0], "IMAGES"); found = {}
for r, _, fs in os.walk(root):
    for f in fs:
        found[os.path.splitext(f)[0].upper()] = os.path.relpath(os.path.join(r, f), sd[0])
n = 0
for pid, bates in db.execute("SELECT id, bates FROM pages WHERE item=? AND bates IS NOT NULL", (a.item,)).fetchall():
    p = found.get(bates.upper())
    if p:
        db.execute("UPDATE pages SET image_path=? WHERE id=?", (p, pid)); n += 1
db.execute("UPDATE pages SET photo=1 WHERE item=? AND image_path IS NOT NULL AND chars<40", (a.item,)) if "photo" in [c[1] for c in db.execute("PRAGMA table_info(pages)")] else None
db.commit(); print(f"done: {len(found)} image files, {n} pages pointed at their image")
