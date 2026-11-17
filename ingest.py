#!/usr/bin/env python3
# (c) 2026 Sunny Chase - Lion Studios. Source-available licence (non-commercial use free; see LICENSE). Built by Sunny Chase (https://github.com/sunnychase) with Claude (Anthropic) · The Epstein Files - Lion Studios
"""ingest.py -- build (or extend) the studio's database from a SOURCE folder of public records. Three source shapes:
  --mode pdf          one or more PDFs; a document boundary is a court docket header ("Case <no> Document <n> Filed <date> Page <i> of <j>")
                      or, when none, the PDF itself (the Internet Archive court-filing items)
  --mode pdfdocs      a production of ONE PDF PER DOCUMENT named by its Bates number (the DOJ EFTA data sets: VOLxxxxx/IMAGES/…/EFTA00001234.pdf);
                      the PDF's own text layer; pages from the PDF
  --mode production   a load-file production with TEXT/…/<BATES>.txt per document, IMAGES/…/<BATES>.jpg per page and a DATA/*.dat
                      Concordance file (þ-delimited) giving BegBates / EndBates (the House Oversight releases); pages = form feeds in the text,
                      else the Bates range; the page image is the Bates-numbered file
Per page: spaCy NER (PERSON, ORG, GPE / LOC / FAC, DATE, MONEY) + regex entities (EMAIL, PHONE, TAIL = aircraft N-number, CASE = docket number) and
REDACTION objects ("Doe 102", "Jane Doe 3", "[REDACTED]", underscore or block runs) kept as objects of their own, never resolved to a person.
mentions = (entity, page, offset, quote); links = co-mention on a page and in a document (weights = page / document counts) with the evidence pages.
Nothing exists without a mention; no link without pages. A re-run of the same --item replaces that item. The docket header, Bates stamps and
"Page i of j" lines are masked before extraction (same offsets), so a stamp never becomes evidence.
  python3 ingest.py --db efiles.db --mode pdf --source data/ia-giuffre-maxwell-1320 --item ia-giuffre-maxwell-1320 --title "…" --url …
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

HDR = re.compile(r"Case\s+(?P<case>\d:\d\d-[a-z]{2}-\d{4,5}(?:-[A-Z]{2,4})?)\s+Document\s+(?P<doc>\d+(?:-\d+)?)\s+Filed\s+(?P<filed>\d\d/\d\d/\d\d)\s+Page\s+(?P<i>\d+)\s+of\s+(?P<j>\d+)", re.I)
BATES = re.compile(r"\b(?:EFTA|HOUSE[ _]OVERSIGHT[ _]|DOJ-OGR-|SDNY_GM_)\s?\d{6,9}\b")
STAMP_SPLIT = re.compile(r"(?<=\bHOUSE[ _]OVERSIGHT[ _]\d{6})[ \t]*\n")      # a production's page stamp ends a page
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<![\d-])(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
TAIL = re.compile(r"\bN\d{3,5}[A-Z]{0,2}\b")
CASENO = re.compile(r"\b\d:\d\d-[a-z]{2}-\d{4,5}\b", re.I)
RED = [("DOE", re.compile(r"\b(?:Jane|John)?\s?Doe\s?(?:No\.?\s?)?#?\s?(\d{1,3})\b", re.I)),
       ("DOE", re.compile(r"\b(Jane Doe|John Doe)\b(?!\s?\d)")),
       ("REDACTED", re.compile(r"\[\s*REDACTED\s*\]|\bREDACTED\b|\bRedacted\b")),
       ("BLOCK", re.compile(r"[_\u2588\u25a0]{5,}"))]
TITLES = {"mr", "mrs", "ms", "dr", "judge", "hon", "honorable", "professor", "prof", "sir", "attorney", "agent", "officer", "det", "detective", "counsel"}
PERSON_STOP = {"jane doe", "john doe", "doe", "plaintiff", "defendant", "exhibit", "deponent", "witness", "counsel", "court", "dear", "sincerely", "regards",
               "pro hac", "hac vice", "protective order", "privilege log", "incident report", "request no", "page", "document", "filed", "case", "allright", "okay", "yes", "no"}
ORG_STOP = {"subpoena", "state", "fed", "court", "u.s", "us", "fbi--", "the fbi", "page", "re", "fw", "fwd", "exhibit", "plaintiff", "defendant", "deposition", "declaration", "affidavit", "order", "motion", "notice", "the court", "district court"}
WORD = re.compile(r"[A-Za-z][A-Za-z'’.-]*")


def pdf_pages(pdf, first=None, last=None):
    """the PDF's pages as text (pdftotext keeps reading order; a form feed ends each page)"""
    cmd = ["pdftotext", "-enc", "UTF-8"] + (["-f", str(first), "-l", str(last)] if first else []) + [pdf, "-"]
    out = subprocess.run(cmd, capture_output=True).stdout.decode("utf-8", "replace")
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def clean_person(s):
    s = re.sub(r"\s+", " ", s).strip(" .,;:'\"()[]")
    toks = [t for t in s.split(" ") if t]
    while toks and toks[0].lower().rstrip(".") in TITLES:
        toks = toks[1:]
    while toks and toks[-1].lower().rstrip(".:") in ("sent", "cc", "to", "from", "subject", "re", "fw", "fwd", "esq", "jr", "sr") and len(toks) > 1 and toks[-1].lower().rstrip(".:") not in ("jr", "sr"):
        toks = toks[:-1]
    if len(toks) >= 2 and toks[-1].lower() == toks[-2].lower():
        toks = toks[:-1]                                      # "Gloria Allred Allred"
    if not 1 <= len(toks) <= 5 or any(not WORD.fullmatch(t) for t in toks):
        return None
    if sum(len(t) for t in toks) < 4 or any(len(t) == 1 and not t.endswith(".") for t in toks):
        return None
    name = " ".join(toks)
    if name.lower() in PERSON_STOP or any(w in name.lower() for w in ("qs ", " qs", "http", "www")) or (len(toks) == 1 and not name[0].isupper()):
        return None
    if name.endswith("'s") or name.endswith("’s"):
        name = name[:-2]
    return name


def norm(name):
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


SCHEMA = """
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, title TEXT, url TEXT, source_dir TEXT, pdf TEXT, mode TEXT, ingested TEXT, pages INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, item TEXT, case_no TEXT, docket TEXT, filed TEXT, title TEXT, first_page INTEGER, last_page INTEGER, npages INTEGER, bates_begin TEXT, bates_end TEXT, path TEXT);
CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, item TEXT, doc_id INTEGER, pdf_page INTEGER, doc_page INTEGER, text TEXT, chars INTEGER, pdf_path TEXT, image_path TEXT, bates TEXT);
CREATE TABLE IF NOT EXISTS entities(id INTEGER PRIMARY KEY, type TEXT, name TEXT, norm TEXT UNIQUE, mentions INTEGER DEFAULT 0, docs INTEGER DEFAULT 0, note TEXT);
CREATE TABLE IF NOT EXISTS aliases(alias_norm TEXT PRIMARY KEY, entity_id INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS mentions(id INTEGER PRIMARY KEY, entity_id INTEGER, page_id INTEGER, doc_id INTEGER, start INTEGER, end INTEGER, quote TEXT, surface TEXT);
CREATE TABLE IF NOT EXISTS links(id INTEGER PRIMARY KEY, a INTEGER, b INTEGER, kind TEXT, weight INTEGER, pages TEXT, docs INTEGER, UNIQUE(a, b, kind));
CREATE INDEX IF NOT EXISTS ix_m_e ON mentions(entity_id); CREATE INDEX IF NOT EXISTS ix_m_p ON mentions(page_id); CREATE INDEX IF NOT EXISTS ix_m_d ON mentions(doc_id);
CREATE INDEX IF NOT EXISTS ix_l_a ON links(a); CREATE INDEX IF NOT EXISTS ix_l_b ON links(b); CREATE INDEX IF NOT EXISTS ix_e_t ON entities(type); CREATE INDEX IF NOT EXISTS ix_p_d ON pages(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(text, content='pages', content_rowid='id', tokenize='porter unicode61');
CREATE TABLE IF NOT EXISTS notebook(id INTEGER PRIMARY KEY, kind TEXT, created TEXT, title TEXT, body TEXT, refs TEXT);
"""


class Ingest:
    def __init__(self, a):
        self.a = a
        import spacy
        self.nlp = spacy.load(a.model, disable=["lemmatizer"]); self.nlp.max_length = 3_000_000
        self.db = sqlite3.connect(a.db, timeout=60); self.db.execute("PRAGMA journal_mode=WAL"); self.db.executescript(SCHEMA)
        self.aliases = {}
        if os.path.exists(a.aliases):
            for canon, alts in json.load(open(a.aliases)).items():
                for x in alts:
                    self.aliases[norm(x)] = canon
        self.ent_ids = {}; self.n_pages = 0; self.n_ment = 0; self.t0 = time.time()

    def entity(self, etype, name):
        key = norm(name)
        if not key:
            return None
        canon = self.aliases.get(key)
        if canon:
            name, key, etype = canon, norm(canon), "PERSON"
        if etype != "PERSON" and (("PERSON", key) in self.ent_ids or self.db.execute("SELECT 1 FROM entities WHERE norm=?", (f"PERSON:{key}",)).fetchone()):
            etype = "PERSON"                                 # an ORG / PLACE hit that names a known person is that person
        k = (etype, key)
        if k not in self.ent_ids:
            row = self.db.execute("SELECT id FROM entities WHERE norm=?", (f"{etype}:{key}",)).fetchone()
            self.ent_ids[k] = row[0] if row else self.db.execute("INSERT INTO entities(type, name, norm) VALUES(?,?,?)", (etype, name, f"{etype}:{key}")).lastrowid
        return self.ent_ids[k]

    def extract(self, text):
        found = []
        body = HDR.sub(lambda mm: " " * len(mm.group(0)), text)      # stamps are not evidence: masked at the same offsets
        body = BATES.sub(lambda mm: " " * len(mm.group(0)), body)
        body = re.sub(r"(?im)^\s*(?:EXHIBIT\s+\w+|Page \d+ of \d+)\s*$", lambda mm: " " * len(mm.group(0)), body)
        if not body.strip():
            return found
        for e in self.nlp(body).ents:
            nm = re.sub(r"\s+", " ", e.text).strip(" .,;:'\"()[]-_|")
            if e.label_ == "PERSON":
                nm = clean_person(e.text)
                if nm: found.append(("PERSON", nm, e.start_char, e.end_char, e.text))
            elif e.label_ == "ORG":
                if 3 <= len(nm) <= 60 and WORD.search(nm) and nm.lower() not in ORG_STOP and nm.lower() not in PERSON_STOP: found.append(("ORG", nm, e.start_char, e.end_char, e.text))
            elif e.label_ in ("GPE", "LOC", "FAC"):
                if 3 <= len(nm) <= 40 and WORD.search(nm): found.append(("PLACE", nm, e.start_char, e.end_char, e.text))
            elif e.label_ == "DATE":
                if re.search(r"\b(19|20)\d\d\b", nm) and len(nm) <= 30: found.append(("DATE", nm, e.start_char, e.end_char, e.text))
            elif e.label_ == "MONEY":
                if re.search(r"\d", nm) and len(nm) <= 24: found.append(("MONEY", nm, e.start_char, e.end_char, e.text))
        for mm in EMAIL.finditer(body): found.append(("EMAIL", mm.group(0).lower(), mm.start(), mm.end(), mm.group(0)))
        for mm in PHONE.finditer(body): found.append(("PHONE", re.sub(r"\D", "", mm.group(0))[-10:], mm.start(), mm.end(), mm.group(0)))
        for mm in TAIL.finditer(body): found.append(("TAIL", mm.group(0), mm.start(), mm.end(), mm.group(0)))
        for mm in CASENO.finditer(body): found.append(("CASE", mm.group(0).lower(), mm.start(), mm.end(), mm.group(0)))
        for kind, rx in RED:
            for mm in rx.finditer(body):
                label = f"Doe {mm.group(1)}" if kind == "DOE" and mm.lastindex and mm.group(1).isdigit() else (mm.group(0).strip() if kind == "DOE" else ("[REDACTED]" if kind == "REDACTED" else "[BLOCK]"))
                found.append(("REDACTION", label, mm.start(), mm.end(), mm.group(0)))
        return found

    def add_page(self, item, doc_id, pdf_page, doc_page, text, pdf_path=None, image_path=None, bates=None):
        c = self.db.execute("INSERT INTO pages(item, doc_id, pdf_page, doc_page, text, chars, pdf_path, image_path, bates) VALUES(?,?,?,?,?,?,?,?,?)", (item, doc_id, pdf_page, doc_page, text, len(text), pdf_path, image_path, bates))
        pid = c.lastrowid; self.n_pages += 1
        self.db.execute("INSERT INTO pages_fts(rowid, text) VALUES(?,?)", (pid, text))
        for etype, name, s, e, surface in self.extract(text):
            eid = self.entity(etype, name)
            if eid is None:
                continue
            qs, qe = max(0, s - 140), min(len(text), e + 140)
            self.db.execute("INSERT INTO mentions(entity_id, page_id, doc_id, start, end, quote, surface) VALUES(?,?,?,?,?,?,?)", (eid, pid, doc_id, s, e, re.sub(r"\s+", " ", text[qs:qe]).strip(), surface))
            self.n_ment += 1
        if self.n_pages % 200 == 0:
            print(f"  page {self.n_pages}: {self.n_ment} mentions, {len(self.ent_ids)} entities ({time.time() - self.t0:.0f}s)", flush=True); self.db.commit()
        return pid

    def doc(self, item, **kw):
        cols = ["item"] + list(kw); vals = [item] + list(kw.values())
        return self.db.execute(f"INSERT INTO documents({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals).lastrowid

    # ---- the three source shapes
    def mode_pdf(self):
        a = self.a; pdfs = sorted(f for f in os.listdir(a.source) if f.lower().endswith(".pdf")); n = 0
        for pdf in pdfs:
            pages = pdf_pages(os.path.join(a.source, pdf)); print(f"{pdf}: {len(pages)} pages", flush=True)
            doc_id = None; cur = None
            for i, text in enumerate(pages, 1):
                m = HDR.search(text[:400]) or HDR.search(text); key = (m.group("case"), m.group("doc")) if m else None
                if key and key != cur:
                    cur = key; doc_id = self.doc(a.item, case_no=m.group("case"), docket=m.group("doc"), filed=m.group("filed"), title=f"Document {m.group('doc')} ({m.group('case')}), filed {m.group('filed')}, {m.group('j')} pages", first_page=i, last_page=i, npages=int(m.group("j")), path=pdf)
                elif doc_id is None:
                    doc_id = self.doc(a.item, case_no="", docket="", filed="", title=f"{pdf} (no docket header)", first_page=i, last_page=i, npages=0, path=pdf)
                self.db.execute("UPDATE documents SET last_page=? WHERE id=?", (i, doc_id))
                self.add_page(a.item, doc_id, i, int(m.group("i")) if m else None, text, pdf_path=pdf)
            n += len(pages)
        return n, ", ".join(pdfs)[:200]

    def mode_pdfdocs(self):
        a = self.a; files = sorted(glob.glob(os.path.join(a.source, "**", "*.pdf"), recursive=True) + glob.glob(os.path.join(a.source, "**", "*.PDF"), recursive=True))
        print(f"{len(files)} per-document PDFs", flush=True); n = 0; seq = 0
        for f in files:
            rel = os.path.relpath(f, a.source); bates = os.path.splitext(os.path.basename(f))[0]
            pages = pdf_pages(f)
            if not pages:
                pages = [""]
            seq += 1; doc_id = self.doc(a.item, case_no="", docket=bates, filed="", title=f"{bates} ({len(pages)} page{'s' if len(pages) != 1 else ''}; {rel.split('/')[0]})", first_page=seq, last_page=seq, npages=len(pages), bates_begin=bates, bates_end=bates, path=rel)
            for i, text in enumerate(pages, 1):
                self.add_page(a.item, doc_id, i, i, text, pdf_path=rel, bates=bates)
            n += len(pages)
        return n, f"{len(files)} PDFs"

    def mode_production(self):
        a = self.a; n = 0
        # the Concordance .dat: þ-quoted, \x14-delimited; the columns BegBates / EndBates (names vary: BEGBATES, Bates Begin, ProdBeg …)
        ranges = {}
        for dat in glob.glob(os.path.join(a.source, "DATA", "**", "*.dat"), recursive=True) + glob.glob(os.path.join(a.source, "**", "*.DAT"), recursive=True):
            raw = open(dat, encoding="utf-8-sig", errors="replace").read()
            for row in csv.reader(raw.splitlines(), delimiter="\x14", quotechar="þ"):
                if not row: continue
                if "beg" in row[0].lower() and "bates" in row[0].lower() or row[0].lower() in ("begbates", "bates begin", "prodbeg", "begdoc"):
                    hdr = [c.lower() for c in row]; continue
                try:
                    ib = next(i for i, c in enumerate(hdr) if "beg" in c); ie = next(i for i, c in enumerate(hdr) if "end" in c and "attach" not in c)
                except (NameError, StopIteration):
                    break
                ranges[row[ib].strip()] = row[ie].strip()
        images = {}
        for f in glob.glob(os.path.join(a.source, "IMAGES", "**", "*.*"), recursive=True):
            images[os.path.splitext(os.path.basename(f))[0]] = os.path.relpath(f, a.source)
        txts = sorted(glob.glob(os.path.join(a.source, "TEXT", "**", "*.txt"), recursive=True))
        print(f"{len(txts)} text documents, {len(ranges)} load-file ranges, {len(images)} page images", flush=True)
        seq = 0
        for f in txts:
            bates = os.path.splitext(os.path.basename(f))[0]; text = open(f, encoding="utf-8-sig", errors="replace").read()
            if "\f" in text:
                pages = text.split("\f")
            else:                                             # no form feeds: the OCR text carries the Bates stamp at the foot of every page; split after each stamp
                parts = STAMP_SPLIT.split(text)
                pages = [x for x in parts if x.strip()] if len(parts) > 1 else [text]
            if pages and not pages[-1].strip() and len(pages) > 1: pages.pop()
            end = ranges.get(bates, bates)
            mnum = re.search(r"(\d+)$", bates); enum = re.search(r"(\d+)$", end)
            npg = (int(enum.group(1)) - int(mnum.group(1)) + 1) if mnum and enum and end.startswith(bates[:mnum.start()]) else len(pages)
            if len(pages) != npg and npg > 0 and len(pages) == 1:
                pages = pages                                  # one text for a multi-page document: kept as one page of text; images per Bates page still listed
            seq += 1; doc_id = self.doc(a.item, case_no="", docket=bates, filed="", title=f"{bates}–{end[-6:] if end != bates else ''} ({npg} page{'s' if npg != 1 else ''})".replace("–  (", " ("), first_page=seq, last_page=seq, npages=npg, bates_begin=bates, bates_end=end, path=os.path.relpath(f, a.source))
            prefix, width = bates[:mnum.start()] if mnum else bates, len(mnum.group(1)) if mnum else 0
            for i, ptxt in enumerate(pages, 1):
                pb = f"{prefix}{int(mnum.group(1)) + i - 1:0{width}d}" if mnum else bates
                self.add_page(a.item, doc_id, i, i, ptxt, image_path=images.get(pb), bates=pb)
            n += len(pages)
        return n, f"{len(txts)} text documents"

    def run(self):
        a = self.a
        if self.db.execute("SELECT 1 FROM pages WHERE item=? LIMIT 1", (a.item,)).fetchone():
            self.db.execute("DELETE FROM mentions WHERE page_id IN (SELECT id FROM pages WHERE item=?)", (a.item,))
            self.db.execute("INSERT INTO pages_fts(pages_fts, rowid, text) SELECT 'delete', id, text FROM pages WHERE item=?", (a.item,))
            self.db.execute("DELETE FROM pages WHERE item=?", (a.item,)); self.db.execute("DELETE FROM documents WHERE item=?", (a.item,))
        n, what = {"pdf": self.mode_pdf, "pdfdocs": self.mode_pdfdocs, "production": self.mode_production}[a.mode]()
        self.db.execute("INSERT OR REPLACE INTO items(id, title, url, source_dir, pdf, mode, ingested, pages, note) VALUES(?,?,?,?,?,?,?,?,?)",
                        (a.item, a.title or a.item, a.url, a.source, what, a.mode, time.strftime("%Y-%m-%dT%H:%M:%S"), n, "spaCy " + a.model))
        self.db.commit()
        if not a.no_rebuild:
            rebuild(self.db)
        st = {t: c for t, c in self.db.execute("SELECT type, COUNT(*) FROM entities GROUP BY type")}
        print(f"done: {self.n_pages} pages, {self.n_ment} mentions this run; entities {st}, links {self.db.execute('SELECT COUNT(*) FROM links').fetchone()[0]} ({time.time() - self.t0:.0f}s)")


def rebuild(db):
    """entity counts and the co-page / co-document links from ALL mentions (the 'emailed' links of extras.py are kept)"""
    print("rebuilding entity counts and links…", flush=True)
    if True:
        db.execute("UPDATE entities SET mentions=(SELECT COUNT(*) FROM mentions m WHERE m.entity_id=entities.id), docs=(SELECT COUNT(DISTINCT doc_id) FROM mentions m WHERE m.entity_id=entities.id)")
        db.execute("DELETE FROM entities WHERE mentions=0"); db.execute("DELETE FROM links WHERE kind IN ('co-page','co-doc')")
        page_ents = collections.defaultdict(set); doc_ents = collections.defaultdict(set)
        for eid, pid, did in db.execute("SELECT entity_id, page_id, doc_id FROM mentions"):
            page_ents[pid].add(eid); doc_ents[did].add(eid)
        co_page = collections.defaultdict(set)
        for pid, es in page_ents.items():
            es = sorted(es)
            if len(es) > 400: continue                      # an index page listing hundreds of names says little about pairs
            for x in range(len(es)):
                for y in range(x + 1, len(es)): co_page[(es[x], es[y])].add(pid)
        co_doc = collections.defaultdict(set)
        for did, es in doc_ents.items():
            es = sorted(es)
            if len(es) > 120: continue                      # co-document pairs only for small documents (a letter, a flight-log page set); no API reads co-doc yet
            for x in range(len(es)):
                for y in range(x + 1, len(es)): co_doc[(es[x], es[y])].add(did)
        db.executemany("INSERT INTO links(a, b, kind, weight, pages, docs) VALUES(?,?,?,?,?,?)", [(k[0], k[1], "co-page", len(v), json.dumps(sorted(v)[:200]), len(v)) for k, v in co_page.items()])
        db.executemany("INSERT INTO links(a, b, kind, weight, pages, docs) VALUES(?,?,?,?,?,?)", [(k[0], k[1], "co-doc", len(v), json.dumps(sorted(v)[:200]), len(v)) for k, v in co_doc.items()])
        db.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True); ap.add_argument("--source", required=True); ap.add_argument("--item", required=True); ap.add_argument("--mode", default="pdf", choices=["pdf", "pdfdocs", "production"])
    ap.add_argument("--title", default=""); ap.add_argument("--url", default=""); ap.add_argument("--aliases", default="aliases.json"); ap.add_argument("--model", default="en_core_web_lg")
    ap.add_argument("--no-rebuild", action="store_true", help="skip the links rebuild (several items in a row: rebuild once at the end)")
    Ingest(ap.parse_args()).run()


if __name__ == "__main__":
    main()
