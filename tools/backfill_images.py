#!/usr/bin/env python3
# (c) 2026 Sunny Chase - Lion Studios. Source-available licence (non-commercial use free; see LICENSE). Built by Sunny Chase (https://github.com/sunnychase) with Claude (Anthropic) · The Epstein Files - Lion Studios
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

# images with no text page (picture pages, blank scans): a page row of their own inside the document whose Bates range covers them
import re
cols = [c[1] for c in db.execute("PRAGMA table_info(pages)")]
have = {b.upper() for (b,) in db.execute("SELECT bates FROM pages WHERE item=? AND bates IS NOT NULL", (a.item,))}
docs = [(d, bb, be) for d, bb, be in db.execute("SELECT id, bates_begin, bates_end FROM documents WHERE item=? AND bates_begin IS NOT NULL", (a.item,))]
def num(b):
    m = re.search(r"(\d+)$", b or ""); return int(m.group(1)) if m else None
ranges = sorted((num(bb), num(be) if be else num(bb), d) for d, bb, be in docs if num(bb) is not None)
added = 0
for stem, rel in found.items():
    if stem in have:
        continue
    k = num(stem)
    if k is None:
        continue
    doc = next((d for lo, hi, d in ranges if lo <= k <= (hi or lo)), None)
    if doc is None:
        continue
    db.execute("INSERT INTO pages(item, doc_id, pdf_page, doc_page, text, chars, image_path, bates%s) VALUES(?,?,?,?,?,?,?,?%s)" % (", photo" if "photo" in cols else "", ", 1" if "photo" in cols else ""),
               (a.item, doc, k, k, "", 0, rel, stem)); added += 1
db.commit(); print(f"added {added} image-only pages (no text layer) to their documents")
