#!/usr/bin/env python3
# Created by Sunny Chase (https://github.com/sunnychase) in collaboration with Claude (Anthropic) · Lion Epstein Files Studio
"""extras.py -- a second pass over the pages already in efiles.db (no NER): e-mails, web links, photo pages.
  * EMAILS: every printed e-mail header block on a page (From / Sent|Date / To / Cc / Subject) -> the `emails` table (page, document, from, to,
    cc, date, subject, each raw line kept) and typed links kind='emailed' between the sender and every recipient the studio can name (a
    PERSON entity by name, else an EMAIL entity by address), with the pages as evidence.
  * URLS: web links in the text -> entities of type URL with their mentions (kept out of the graph unless asked).
  * PHOTOS: pages whose text is a stamp or nothing (< 120 characters) in a document with a PDF or an image -> `pages.photo = 1`, so the
    Photos tab can show them as thumbnails (what the page shows is for the eye; the studio reads nothing into a picture).
Idempotent: re-run after every ingest (it rebuilds its own tables and the 'emailed' links only).
  python3 extras.py --db efiles.db
"""
import argparse
import collections
import json
import re
import sqlite3
import time

HDR = re.compile(r"^[ \t>]*(From|Sent|Date|To|Cc|CC|Bcc|Subject|Subj)\s*:\s*(.*)$", re.M)
URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]{4,}", re.I)
ADDR = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def norm(name):
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def parties(raw):
    """'Jeffrey Epstein [mailto:jeevacation@gmail.com]; Smith, John <john@x.com>' -> [(name, address), …]"""
    out = []
    for part in re.split(r"[;,](?![^<]*>)|\s{2,}(?=[A-Z])", raw):
        part = part.strip(" \t'\"")
        if not part:
            continue
        addr = ADDR.search(part); a = addr.group(0).lower() if addr else None
        name = re.sub(r"\[mailto:[^\]]*\]|<[^>]*>|\([^)]*\)|" + (re.escape(addr.group(0)) if addr else "$^"), "", part).strip(" \t'\"<>[]")
        name = re.sub(r"\s+", " ", name)
        if re.fullmatch(r"(?i)(?:[a-z]+), (?:[a-z]+(?: [a-z]\.?)?)", name):     # "Last, First" -> "First Last"
            last, first = name.split(", ", 1); name = f"{first} {last}"
        if len(name) < 3 or re.search(r"\d{3}", name):
            name = None
        if name or a:
            out.append((name, a))
    return out[:12]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    db = sqlite3.connect(a.db, timeout=120); db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS emails(id INTEGER PRIMARY KEY, page_id INTEGER, doc_id INTEGER, from_raw TEXT, to_raw TEXT, cc_raw TEXT, date_raw TEXT, subject TEXT, from_id INTEGER, to_ids TEXT);
    CREATE INDEX IF NOT EXISTS ix_em_p ON emails(page_id); CREATE INDEX IF NOT EXISTS ix_em_f ON emails(from_id); CREATE INDEX IF NOT EXISTS ix_em_d ON emails(doc_id);
    CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(from_raw, to_raw, cc_raw, subject, content='emails', content_rowid='id', tokenize='porter unicode61');
    """)
    try:
        db.execute("ALTER TABLE pages ADD COLUMN photo INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    db.execute("DELETE FROM emails"); db.execute("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')")
    db.execute("DELETE FROM links WHERE kind='emailed'")
    db.execute("DELETE FROM mentions WHERE entity_id IN (SELECT id FROM entities WHERE type='URL')"); db.execute("DELETE FROM entities WHERE type='URL'")
    person = {r[0][7:]: r[1] for r in db.execute("SELECT norm, id FROM entities WHERE type='PERSON'")}
    emailent = {r[0][6:]: r[1] for r in db.execute("SELECT norm, id FROM entities WHERE type='EMAIL'")}
    urls = {}; t0 = time.time(); n_em = 0; n_url = 0; emailed = collections.defaultdict(set)

    owners = {}
    try:
        owners = {k.lower(): v for k, v in json.load(open("email_owners.json")).items() if not k.startswith("_")}
    except (OSError, ValueError):
        pass

    def ent_for(name, addr):
        if addr and addr.lower() in owners and norm(owners[addr.lower()]) in person:
            return person[norm(owners[addr.lower()])]          # a documented address of a known person -> the person
        if name and norm(name) in person:
            return person[norm(name)]
        if addr and norm(addr) in emailent:
            return emailent[norm(addr)]
        if addr:
            k = norm(addr); cur = db.execute("INSERT INTO entities(type, name, norm) VALUES(?,?,?)", ("EMAIL", addr, f"EMAIL:{k}")); emailent[k] = cur.lastrowid
            return cur.lastrowid
        return None

    for pid, did, text, chars, pdf_path, image_path in db.execute("SELECT id, doc_id, text, chars, pdf_path, image_path FROM pages"):
        if chars < 120 and (pdf_path or image_path):
            db.execute("UPDATE pages SET photo=1 WHERE id=?", (pid,))
        # web links
        for m in URL.finditer(text or ""):
            u = m.group(0).rstrip(".,;:)'\"").lower(); k = norm(u)[:120]
            if not k:
                continue
            if k not in urls:
                urls[k] = db.execute("INSERT INTO entities(type, name, norm) VALUES(?,?,?)", ("URL", u[:200], f"URL:{k}")).lastrowid
            qs, qe = max(0, m.start() - 100), min(len(text), m.end() + 100)
            db.execute("INSERT INTO mentions(entity_id, page_id, doc_id, start, end, quote, surface) VALUES(?,?,?,?,?,?,?)", (urls[k], pid, did, m.start(), m.end(), re.sub(r"\s+", " ", text[qs:qe]), m.group(0))); n_url += 1
        # e-mail header blocks: a From line followed within 8 lines by To or Subject
        hs = list(HDR.finditer(text or ""))
        i = 0
        while i < len(hs):
            if hs[i].group(1).lower() != "from":
                i += 1; continue
            block = {"from": hs[i].group(2).strip()}; j = i + 1; start_line = text.count("\n", 0, hs[i].start())
            while j < len(hs) and text.count("\n", 0, hs[j].start()) - start_line <= 8 and hs[j].group(1).lower() != "from":
                k = hs[j].group(1).lower(); k = {"sent": "date", "subj": "subject", "cc": "cc"}.get(k, k)
                block.setdefault(k, hs[j].group(2).strip()); j += 1
            if "to" in block or "subject" in block:
                fr = parties(block["from"]); to = parties(block.get("to", "")) + parties(block.get("cc", ""))
                fid = ent_for(*fr[0]) if fr else None; tids = [x for x in (ent_for(n, ad) for n, ad in to) if x]
                db.execute("INSERT INTO emails(page_id, doc_id, from_raw, to_raw, cc_raw, date_raw, subject, from_id, to_ids) VALUES(?,?,?,?,?,?,?,?,?)",
                           (pid, did, block["from"][:300], block.get("to", "")[:600], block.get("cc", "")[:600], block.get("date", "")[:80], block.get("subject", "")[:300], fid, json.dumps(tids)))
                n_em += 1
                if fid:
                    for t in tids:
                        if t != fid:
                            emailed[(min(fid, t), max(fid, t))].add(pid)
            i = j
    db.execute("INSERT INTO emails_fts(emails_fts) VALUES('rebuild')")
    db.executemany("INSERT OR REPLACE INTO links(a, b, kind, weight, pages, docs) VALUES(?,?,?,?,?,?)", [(k[0], k[1], "emailed", len(v), json.dumps(sorted(v)[:200]), len(v)) for k, v in emailed.items()])
    db.execute("UPDATE entities SET mentions=(SELECT COUNT(*) FROM mentions m WHERE m.entity_id=entities.id), docs=(SELECT COUNT(DISTINCT doc_id) FROM mentions m WHERE m.entity_id=entities.id) WHERE type IN ('URL','EMAIL')")
    db.commit()
    print(f"done: {n_em} e-mail headers, {len(emailed)} emailed links, {len(urls)} web links ({n_url} mentions), photo pages {db.execute('SELECT COUNT(*) FROM pages WHERE photo=1').fetchone()[0]} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
