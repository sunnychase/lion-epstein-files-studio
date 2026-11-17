#!/usr/bin/env python3
# (c) 2026 Sunny Chase - Lion Studios. All rights reserved. Proprietary. Built by Sunny Chase (https://github.com/sunnychase) with Claude (Anthropic) · The Epstein Files - Lion Studios
"""server.py -- the studio's server: Python standard library only (http.server + sqlite3), the static front end in static/.
Reads efiles.db (built by ingest.py); renders page images with pdftoppm on demand (cached); keeps the case notebook in the same database.
Every answer is grounded in the documents: entities come with their mentions (page + quote), links with the pages that are their evidence.
The app never proposes an identity for a redacted party: REDACTION entities are objects of their own, shown with their context only.
Settings (environment): EFILES_HOST (default 127.0.0.1), EFILES_PORT (8670), EFILES_DB (efiles.db), EFILES_DATA (data/), EFILES_CACHE (cache/).
API (GET unless said): /api/stats · /api/search?q=&limit= (FTS5: phrases "…", AND/OR/NOT, NEAR(a b, 5)) · /api/entities?type=&q=&sort=&limit=
· /api/entity/<id> · /api/graph?center=<id>&depth=1|2&min=<weight>&types=PERSON,ORG&limit= · /api/path?a=<id>&b=<id>&max=4
· /api/doc/<id> · /api/page/<id> · /page/<id>.png · /api/redactions · /api/timeline?entity=<id> · /api/notebook (GET; POST {kind,title,body,refs}; DELETE ?id=)
"""
import collections
import heapq
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("EFILES_HOST", "127.0.0.1"); PORT = int(os.environ.get("EFILES_PORT", "8670"))
DB = os.environ.get("EFILES_DB", os.path.join(ROOT, "efiles.db")); DATA = os.environ.get("EFILES_DATA", os.path.join(ROOT, "data"))
CACHE = os.environ.get("EFILES_CACHE", os.path.join(ROOT, "cache")); os.makedirs(CACHE, exist_ok=True)
PRODUCT = "The Epstein Files - Lion Studios"
COPYRIGHT = "(c) 2026 Sunny Chase - Lion Studios. All rights reserved."
_local = threading.local()
_render_lock = threading.Lock()


def db():
    c = getattr(_local, "db", None)
    if c is None:
        c = _local.db = sqlite3.connect(DB, check_same_thread=False, timeout=30); c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")            # readers never wait on an ingest in progress
            c.execute("CREATE TABLE IF NOT EXISTS profiles(entity_id INTEGER PRIMARY KEY, title TEXT, description TEXT, extract TEXT, url TEXT, category TEXT, checked TEXT, found INTEGER)")
            c.execute("CREATE TABLE IF NOT EXISTS emails(id INTEGER PRIMARY KEY, page_id INTEGER, doc_id INTEGER, from_raw TEXT, to_raw TEXT, cc_raw TEXT, date_raw TEXT, subject TEXT, from_id INTEGER, to_ids TEXT)")
            c.commit()
        except sqlite3.OperationalError:
            pass
    return c


def rows(sql, args=()):
    return [dict(r) for r in db().execute(sql, args)]


def one(sql, args=()):
    r = db().execute(sql, args).fetchone()
    return dict(r) if r else None


def fts_query(q):
    """the user's query into FTS5 syntax: bare words AND-ed, quotes kept, the words AND OR NOT NEAR kept, everything else escaped"""
    q = q.strip()
    if not q:
        return ""
    toks = re.findall(r'"[^"]*"|NEAR\([^)]*\)|\S+', q)
    out = []
    for t in toks:
        if t.startswith('"') or t.startswith("NEAR("):
            out.append(t)
        elif t.upper() in ("AND", "OR", "NOT"):
            out.append(t.upper())
        else:
            out.append('"' + t.replace('"', "") + '"' + ("*" if t.endswith("*") else ""))
    return " ".join(out)


def hidden_ids():
    try:
        names = [n for n in json.load(open(os.path.join(ROOT, "suppressed.json"))) if isinstance(n, str)]
    except (OSError, ValueError):
        names = []
    if not names:
        return set()
    norms = [re.sub(r"[^a-z0-9 ]", "", n.lower()).strip() for n in names]
    return {r["id"] for r in rows("SELECT id FROM entities WHERE type='PERSON' AND substr(norm, 8) IN (%s)" % ",".join("?" * len(norms)), norms)}


def api_stats():
    st = {r["type"]: r["n"] for r in rows("SELECT type, COUNT(*) n FROM entities GROUP BY type")}
    return {"copyright": COPYRIGHT, "product": PRODUCT, "items": rows("SELECT id, title, url, pages, mode, ingested FROM items"), "documents": one("SELECT COUNT(*) n FROM documents")["n"],
            "pages": one("SELECT COUNT(*) n FROM pages")["n"], "mentions": one("SELECT COUNT(*) n FROM mentions")["n"], "entities": st,
            "links": one("SELECT COUNT(*) n FROM links")["n"], "notebook": one("SELECT COUNT(*) n FROM notebook")["n"]}


def api_search(p):
    q = fts_query(p.get("q", "")); limit = min(int(p.get("limit", 50)), 200)
    if not q:
        return {"q": "", "hits": []}
    try:
        hits = rows("SELECT p.id page_id, p.pdf_page, p.doc_id, d.title doc_title, d.docket, snippet(pages_fts, 0, '[[', ']]', '…', 28) snip, bm25(pages_fts) score "
                    "FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid JOIN documents d ON d.id = p.doc_id WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT ?", (q, limit))
    except sqlite3.OperationalError as e:
        return {"q": q, "error": f"query not understood: {e}", "hits": []}
    for h in hits:
        h["entities"] = rows("SELECT e.id, e.type, e.name FROM mentions m JOIN entities e ON e.id = m.entity_id WHERE m.page_id = ? GROUP BY e.id ORDER BY e.type, e.name LIMIT 40", (h["page_id"],))
    return {"q": q, "hits": hits, "total": one("SELECT COUNT(*) n FROM pages_fts WHERE pages_fts MATCH ?", (q,))["n"]}


def api_entities(p):
    t = p.get("type", ""); q = p.get("q", "").strip().lower(); sort = p.get("sort", "mentions"); limit = min(int(p.get("limit", 100)), 2000)
    sql = "SELECT id, type, name, mentions, docs FROM entities WHERE 1=1"; args = []
    hid = hidden_ids()
    if hid:
        sql += " AND id NOT IN (%s)" % ",".join(map(str, hid))
    if t:
        sql += " AND type IN (%s)" % ",".join("?" * len(t.split(","))); args += t.split(",")
    if q:
        sql += " AND lower(name) LIKE ?"; args.append(f"%{q}%")
    sql += " ORDER BY " + {"mentions": "mentions DESC, docs DESC", "docs": "docs DESC, mentions DESC", "name": "name"}.get(sort, "mentions DESC") + " LIMIT ?"; args.append(limit)
    return {"entities": rows(sql, args)}


def api_entity(eid, p):
    e = one("SELECT * FROM entities WHERE id=?", (eid,))
    if not e:
        return {"error": "no such entity"}
    e["aliases"] = [r["alias_norm"] for r in rows("SELECT alias_norm FROM aliases WHERE entity_id=?", (eid,))]
    e["documents"] = rows("SELECT d.id, d.docket, d.title, d.filed, COUNT(*) n, MIN(p.pdf_page) first_page FROM mentions m JOIN documents d ON d.id=m.doc_id JOIN pages p ON p.id=m.page_id WHERE m.entity_id=? GROUP BY d.id ORDER BY n DESC", (eid,))
    e["mentions"] = rows("SELECT m.id, m.page_id, p.pdf_page, m.doc_id, d.docket, m.quote, m.surface FROM mentions m JOIN pages p ON p.id=m.page_id JOIN documents d ON d.id=m.doc_id WHERE m.entity_id=? ORDER BY p.pdf_page LIMIT ?", (eid, min(int(p.get("limit", 300)), 2000)))
    e["connections"] = rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END other_id, x.type, x.name, l.kind, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END "
                            "WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type NOT IN ('CASE','DATE','MONEY','URL') ORDER BY l.weight DESC, x.mentions DESC LIMIT 200", (eid, eid, eid, eid))
    e["emailed"] = rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END other_id, x.type, x.name, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='emailed' ORDER BY l.weight DESC LIMIT 100", (eid, eid, eid, eid))
    for c in e["emailed"]:
        c["pages"] = json.loads(c["pages"])[:8]
    e["profile"] = one("SELECT title, description, extract, url, category FROM profiles WHERE entity_id=? AND found=1", (eid,))
    e["photos"] = one("SELECT COUNT(DISTINCT p.id) n FROM mentions m JOIN pages p ON p.doc_id=m.doc_id WHERE m.entity_id=? AND p.photo=1", (eid,))["n"]
    for c in e["connections"]:
        c["pages"] = json.loads(c["pages"])[:12]
    return e


def api_graph(p):
    center = p.get("center"); depth = min(int(p.get("depth", 1)), 2); minw = int(p.get("min", 1)); limit = min(int(p.get("limit", 120)), 400)
    kind = p.get("kind", "co-page") if p.get("kind") in ("co-page", "emailed", "paid") else "co-page"
    types = [t for t in p.get("types", "PERSON,ORG,PLACE,REDACTION,EMAIL,PHONE,TAIL").split(",") if t]
    tsel = " AND x.type IN (%s)" % ",".join("?" * len(types))
    if center:
        seeds = {int(center)}; nodes = {int(center)}; edges = {}; hop = {int(center): 0}
        for h in range(depth):
            frontier = set()
            for s in list(seeds):
                for r in rows("SELECT l.a, l.b, l.weight, l.kind FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind=? AND l.weight>=?" + tsel + " ORDER BY l.weight DESC LIMIT ?",
                              [s, s, s, kind, minw] + types + [limit]):
                    o = r["b"] if r["a"] == s else r["a"]
                    edges[(min(r["a"], r["b"]), max(r["a"], r["b"]))] = r["weight"]; frontier.add(o); hop.setdefault(o, h + 1)
            nodes |= frontier; seeds = frontier - nodes if False else frontier
            if len(nodes) > limit * 3:
                break
        ids = list(nodes)
    else:   # the overview: the heaviest entities of the chosen types and the links among them
        ids = [r["id"] for r in rows("SELECT id FROM entities x WHERE 1=1" + tsel + " ORDER BY mentions DESC LIMIT ?", types + [limit])]
        edges = {}; hop = {}
    idset = set(ids)
    if ids:
        for r in rows("SELECT a, b, weight FROM links WHERE kind=? AND weight>=? AND a IN (%s) AND b IN (%s)" % (",".join(map(str, ids)), ",".join(map(str, ids))), (kind, minw)):
            if r["a"] in idset and r["b"] in idset:
                edges[(r["a"], r["b"])] = r["weight"]
    hid = hidden_ids(); ids = [i for i in ids if i not in hid]
    ents = rows("SELECT e.id, e.type, e.name, e.mentions, e.docs, p.category, p.description FROM entities e LEFT JOIN profiles p ON p.entity_id=e.id AND p.found=1 WHERE e.id IN (%s)" % ",".join(map(str, ids))) if ids else []
    for e in ents:
        e["hop"] = hop.get(e["id"])
    return {"nodes": ents, "edges": [{"a": a, "b": b, "w": w} for (a, b), w in edges.items()], "kind": kind}


def api_path(p):
    a, b = int(p.get("a", 0)), int(p.get("b", 0)); maxlen = min(int(p.get("max", 4)), 6)
    kind = p.get("kind", "co-page") if p.get("kind") in ("co-page", "emailed", "paid") else "co-page"
    if not a or not b:
        return {"error": "give a and b"}
    # Dijkstra over co-page links; cost = 1 / weight so heavier (more shared pages) links are preferred, at most maxlen hops
    best = {a: (0.0, 0)}; prev = {}; heap = [(0.0, 0, a)]
    while heap:
        cost, hops, n = heapq.heappop(heap)
        if n == b:
            break
        if hops >= maxlen or cost > best.get(n, (1e9,))[0]:
            continue
        for r in rows("SELECT l.a, l.b, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE l.kind=? AND (l.a=? OR l.b=?) AND x.type IN ('PERSON','ORG','PLACE','REDACTION','EMAIL','PHONE','TAIL')", (n, kind, n, n)):
            o = r["b"] if r["a"] == n else r["a"]; c = cost + 1.0 / (1 + r["weight"])
            if c < best.get(o, (1e9,))[0]:
                best[o] = (c, hops + 1); prev[o] = (n, r["weight"]); heapq.heappush(heap, (c, hops + 1, o))
    if b not in prev and a != b:
        return {"path": [], "note": f"no chain of shared pages within {maxlen} hops"}
    chain = []; n = b
    while n != a:
        pn, w = prev[n]; chain.append((pn, n, w)); n = pn
    chain.reverse()
    out = []
    for x, y, w in chain:
        l = one("SELECT pages FROM links WHERE kind=? AND a=? AND b=?", (kind, min(x, y), max(x, y)))
        pages = json.loads(l["pages"])[:6] if l else []
        ev = []
        for pid in pages[:3]:
            qx = one("SELECT quote FROM mentions WHERE entity_id=? AND page_id=? LIMIT 1", (x, pid)); qy = one("SELECT quote FROM mentions WHERE entity_id=? AND page_id=? LIMIT 1", (y, pid))
            pg = one("SELECT p.pdf_page, d.docket FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", (pid,))
            ev.append({"page_id": pid, "pdf_page": pg["pdf_page"], "docket": pg["docket"], "quote_a": qx["quote"] if qx else "", "quote_b": qy["quote"] if qy else ""})
        out.append({"from": one("SELECT id, type, name FROM entities WHERE id=?", (x,)), "to": one("SELECT id, type, name FROM entities WHERE id=?", (y,)), "shared_pages": w, "evidence": ev})
    return {"path": out, "kind": kind}


def api_doc(did):
    d = one("SELECT d.*, i.title item_title, i.url FROM documents d JOIN items i ON i.id=d.item WHERE d.id=?", (did,))
    if not d:
        return {"error": "no such document"}
    d["pages"] = rows("SELECT id, pdf_page, doc_page, chars FROM pages WHERE doc_id=? ORDER BY pdf_page", (did,))
    d["entities"] = rows("SELECT e.id, e.type, e.name, COUNT(*) n FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE m.doc_id=? GROUP BY e.id ORDER BY n DESC LIMIT 300", (did,))
    return d


def api_page(pid):
    pg = one("SELECT p.*, d.docket, d.title doc_title, d.case_no FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", (pid,))
    if not pg:
        return {"error": "no such page"}
    pg["mentions"] = rows("SELECT m.id, m.entity_id, e.type, e.name, m.start, m.end, m.surface FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE m.page_id=? ORDER BY m.start", (pid,))
    nb = one("SELECT id FROM pages WHERE id>? AND item=? ORDER BY id LIMIT 1", (pid, pg["item"])); pv = one("SELECT id FROM pages WHERE id<? AND item=? ORDER BY id DESC LIMIT 1", (pid, pg["item"]))
    pg["next_id"] = nb["id"] if nb else None; pg["prev_id"] = pv["id"] if pv else None
    return pg


def page_png(pid):
    """-> (path, content type): the page's own image file (a production's IMAGES/…), else a render of its PDF page (cached)"""
    pg = one("SELECT p.item, p.pdf_page, p.pdf_path, p.image_path, i.source_dir, i.pdf FROM pages p JOIN items i ON i.id=p.item WHERE p.id=?", (pid,))
    if not pg:
        return None, None
    sd = pg["source_dir"] if os.path.isabs(pg["source_dir"]) else os.path.join(ROOT, pg["source_dir"])
    if pg["image_path"]:
        f = os.path.join(sd, pg["image_path"])
        return (f, "image/jpeg" if f.lower().endswith((".jpg", ".jpeg")) else "image/png" if f.lower().endswith(".png") else "image/tiff") if os.path.exists(f) else (None, None)
    pdf = pg["pdf_path"] or pg["pdf"]
    if not pdf:
        return None, None
    out = os.path.join(CACHE, re.sub(r"[^A-Za-z0-9._-]", "_", f"{pg['item']}-{pdf}-{pg['pdf_page']}") + ".png")
    if not os.path.exists(out):
        with _render_lock:
            if not os.path.exists(out):
                subprocess.run(["pdftoppm", "-f", str(pg["pdf_page"]), "-l", str(pg["pdf_page"]), "-r", "110", "-png", "-singlefile", os.path.join(sd, pdf), out[:-4]], check=True, timeout=120)
    return out, "image/png"


def api_redactions(p):
    red = rows("SELECT e.id, e.name, e.mentions, e.docs FROM entities e WHERE e.type='REDACTION' ORDER BY e.mentions DESC")
    for r in red:
        r["documents"] = rows("SELECT d.id, d.docket, COUNT(*) n FROM mentions m JOIN documents d ON d.id=m.doc_id WHERE m.entity_id=? GROUP BY d.id ORDER BY n DESC LIMIT 20", (r["id"],))
        r["context"] = rows("SELECT x.id, x.type, x.name, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type<>'REDACTION' ORDER BY l.weight DESC LIMIT 25", (r["id"], r["id"], r["id"]))
    return {"redactions": red, "note": "Redacted parties are kept redacted: the studio shows the documents, pages and named context around each redaction and never proposes who a redacted person is."}


def api_timeline(p):
    eid = int(p.get("entity", 0))
    dates = rows("SELECT x.name date_text, l.weight, l.pages FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='DATE' ORDER BY l.weight DESC LIMIT 300", (eid, eid, eid))
    out = []
    for d in dates:
        y = re.search(r"\b(19|20)\d\d\b", d["date_text"])
        out.append({"date": d["date_text"], "year": int(y.group(0)) if y else None, "pages": json.loads(d["pages"])[:6], "weight": d["weight"]})
    out.sort(key=lambda x: (x["year"] or 9999, x["date"]))
    return {"entity": eid, "dates": out}


THEMES = [("blackmail / extortion", '"blackmail" OR "extort" OR "extortion" OR "leverage" OR "compromis*"'), ("cameras / recordings", '"camera" OR "cameras" OR "videotape" OR "recording" OR "recorded" OR "surveillance" OR "hidden"'),
          ("trafficking / minors", '"trafficking" OR "minor" OR "underage" OR "under age" OR "recruit*"'), ("massage", '"massage" OR "masseuse" OR "massages"'),
          ("flights / aircraft", '"flight log" OR "flight logs" OR "manifest" OR "jet" OR "N908JE" OR "pilot"'), ("money / payments", '"wire transfer" OR "payment" OR "paid" OR "invoice" OR "settlement" OR "trust"'),
          ("island / properties", '"Little St" OR "island" OR "Zorro" OR "ranch" OR "Palm Beach" OR "71st Street" OR "Paris apartment"'), ("intelligence / agencies", '"intelligence" OR "Mossad" OR "CIA" OR "FBI" OR "informant" OR "cooperat*"'),
          ("non-prosecution / plea", '"non-prosecution" OR "NPA" OR "plea" OR "immunity" OR "co-conspirator"'), ("phones / contacts", '"black book" OR "contact" OR "phone number" OR "address book"'),
          ("named as participants", '"co-conspirator" OR "co-conspirators" OR "accomplice" OR "accomplices" OR "recruiter" OR "recruiters" OR "scheduled" OR "assistant" OR "procured"')]


def api_themes(p):
    out = []
    for name, q in THEMES:
        try:
            n = one("SELECT COUNT(*) n FROM pages_fts WHERE pages_fts MATCH ?", (q,))["n"]
        except sqlite3.OperationalError:
            n = -1
        out.append({"theme": name, "q": q, "pages": n})
    return {"themes": out, "note": "Each lead is a saved full-text search. A matching page is a page that uses the words, nothing more: read the quotes and judge."}


def api_emails(p):
    q = p.get("q", "").strip(); who = p.get("who", "").strip().lower(); limit = min(int(p.get("limit", 200)), 1000)
    sql = ("SELECT m.id, m.page_id, m.doc_id, d.docket, m.from_raw, m.to_raw, m.cc_raw, m.date_raw, m.subject, m.from_id, f.name from_name, m.to_ids FROM emails m JOIN documents d ON d.id=m.doc_id LEFT JOIN entities f ON f.id=m.from_id")
    args = []; where = []
    if q:
        where.append("m.id IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ?)"); args.append(fts_query(q))
    if who:
        where.append("(lower(m.from_raw) LIKE ? OR lower(m.to_raw) LIKE ? OR lower(m.cc_raw) LIKE ?)"); args += [f"%{who}%"] * 3
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.id LIMIT ?"; args.append(limit)
    try:
        em = rows(sql, args)
    except sqlite3.OperationalError as e:
        return {"emails": [], "error": str(e)}
    ids = {i for e in em for i in json.loads(e["to_ids"] or "[]")}
    names = {r["id"]: r["name"] for r in rows("SELECT id, name FROM entities WHERE id IN (%s)" % ",".join(map(str, ids)))} if ids else {}
    for e in em:
        e["to_names"] = [names.get(i) for i in json.loads(e["to_ids"] or "[]") if i in names]
    tot = one("SELECT COUNT(*) n FROM emails")["n"]
    senders = rows("SELECT e.id, e.name, COUNT(*) n FROM emails m JOIN entities e ON e.id=m.from_id GROUP BY e.id ORDER BY n DESC LIMIT 40")
    return {"emails": em, "total": tot, "senders": senders}


def api_photos(p):
    did = p.get("doc"); ent = p.get("entity"); limit = min(int(p.get("limit", 120)), 600); offset = int(p.get("offset", 0))
    if ent:
        pg = rows("SELECT DISTINCT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM mentions m JOIN pages p ON p.doc_id=m.doc_id JOIN documents d ON d.id=p.doc_id WHERE m.entity_id=? AND p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", (int(ent), limit, offset))
        note = "photo pages in the documents that mention this person (the picture itself is not read; the document's text is the only link)"
    elif did:
        pg = rows("SELECT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.doc_id=? AND p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", (int(did), limit, offset)); note = ""
    else:
        pg = rows("SELECT p.id, p.pdf_page, p.doc_id, d.docket, p.bates FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.photo=1 ORDER BY p.id LIMIT ? OFFSET ?", (limit, offset)); note = "every page that is a picture (a stamp or no text), newest items last"
    return {"pages": pg, "total": one("SELECT COUNT(*) n FROM pages WHERE photo=1")["n"], "note": note}


def api_figures(p):
    cat = p.get("category", ""); focus = one("SELECT id FROM entities WHERE norm='PERSON:jeffrey epstein'")
    fid = focus["id"] if focus else 0
    sql = ("SELECT e.id, e.name, e.mentions, e.docs, p.category, p.description, p.url, p.extract, COALESCE(l.weight, 0) shared "
           "FROM profiles p JOIN entities e ON e.id=p.entity_id LEFT JOIN links l ON l.kind='co-page' AND ((l.a=? AND l.b=e.id) OR (l.b=? AND l.a=e.id)) WHERE p.found=1")
    args = [fid, fid]
    if cat:
        sql += " AND p.category=?"; args.append(cat)
    sql += " ORDER BY shared DESC, e.mentions DESC LIMIT 800"
    fig = rows(sql, args)
    cats = rows("SELECT category, COUNT(*) n FROM profiles WHERE found=1 GROUP BY category ORDER BY n DESC")
    return {"figures": fig, "categories": cats, "focus": "Jeffrey Epstein", "note": "A public figure here is a person named in the files whose name is the exact title of a Wikipedia article (a same-name person is possible; the files are the evidence). 'Shared' = pages on which both the figure and Jeffrey Epstein are mentioned."}


def thumb_png(pid):
    f, ct = page_png(pid)
    if not f:
        return None, None
    if ct != "image/png":
        return f, ct
    out = os.path.join(CACHE, "thumb-" + os.path.basename(f))
    if not os.path.exists(out):
        pg = one("SELECT p.pdf_page, p.pdf_path, i.source_dir, i.pdf FROM pages p JOIN items i ON i.id=p.item WHERE p.id=?", (pid,))
        sd = pg["source_dir"] if os.path.isabs(pg["source_dir"]) else os.path.join(ROOT, pg["source_dir"])
        with _render_lock:
            if not os.path.exists(out):
                subprocess.run(["pdftoppm", "-f", str(pg["pdf_page"]), "-l", str(pg["pdf_page"]), "-r", "28", "-png", "-singlefile", os.path.join(sd, pg["pdf_path"] or pg["pdf"]), out[:-4]], check=True, timeout=120)
    return out, "image/png"


_DASH = {"t": 0, "d": None}


def api_dashboard(p):
    """one call for the landing page: leads, the strongest connections, e-mail traffic, public figures, unknown heavy hitters, redactions, the notebook (cached 10 min)"""
    if _DASH["d"] and time.time() - _DASH["t"] < 600 and not p.get("fresh"):
        return _DASH["d"]
    focus = one("SELECT id FROM entities WHERE norm='PERSON:jeffrey epstein'"); fid = focus["id"] if focus else 0
    d = {"stats": api_stats(), "themes": api_themes({})["themes"]}
    d["pairs"] = rows("SELECT a.name a_name, a.id a_id, b.name b_name, b.id b_id, l.weight FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='co-page' AND a.type='PERSON' AND b.type='PERSON' "
                      "AND a.name LIKE '% %' AND b.name LIKE '% %' AND a.name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND b.name NOT GLOB '*[A-Z][A-Z][A-Z]*' ORDER BY l.weight DESC LIMIT 40")
    d["emailed"] = rows("SELECT a.name a_name, a.id a_id, b.name b_name, b.id b_id, l.weight FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='emailed' ORDER BY l.weight DESC LIMIT 30")
    d["correspondents"] = rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END id, x.name, x.type, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='emailed' ORDER BY l.weight DESC LIMIT 30", (fid, fid, fid, fid))
    fig = api_figures({})["figures"]
    bycat = {}
    for f in fig:
        bycat.setdefault(f["category"], []).append(f)
    d["figures"] = {c: v[:12] for c, v in bycat.items()}
    d["unknown"] = rows("SELECT e.id, e.name, e.mentions, e.docs, COALESCE(l.weight,0) shared FROM entities e LEFT JOIN profiles p ON p.entity_id=e.id LEFT JOIN links l ON l.kind='co-page' AND ((l.a=? AND l.b=e.id) OR (l.b=? AND l.a=e.id)) "
                       "WHERE e.type='PERSON' AND (p.found IS NULL OR p.found=0) AND e.name LIKE '% %' AND e.name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND e.id<>? ORDER BY shared DESC, e.mentions DESC LIMIT 40", (fid, fid, fid))
    d["redactions"] = api_redactions({})["redactions"][:12]
    d["notebook"] = rows("SELECT id, kind, created, title, substr(body,1,240) body FROM notebook ORDER BY id DESC LIMIT 12")
    d["items"] = rows("SELECT id, title, pages, mode, ingested FROM items ORDER BY ingested")
    d["tails"] = rows("SELECT id, name, mentions, docs FROM entities WHERE type='TAIL' ORDER BY mentions DESC LIMIT 12")
    try:
        ms = api_money_summary({}); d["money"] = {"total": ms["total"], "flags": ms["flags"], "pairs": ms["pairs"][:10], "banks": ms["banks"][:8], "structuring": ms["structuring"][:6], "biggest": ms["biggest"][:6]}
    except sqlite3.OperationalError:
        d["money"] = None
    try:   # persons of interest: the people (not Epstein / Maxwell, not public figures) most mentioned on pages that speak of co-conspirators, accomplices, recruiters, assistants
        d["participants"] = rows("SELECT e.id, e.name, COUNT(DISTINCT m.page_id) n, COUNT(DISTINCT m.doc_id) docs FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='PERSON' AND e.name LIKE '% %' AND e.name NOT GLOB '*[A-Z][A-Z][A-Z]*' "
                                 "AND e.norm NOT IN ('PERSON:jeffrey epstein','PERSON:ghislaine maxwell') AND e.id NOT IN (SELECT entity_id FROM profiles WHERE found=1) "
                                 "AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?) GROUP BY e.id HAVING n>=4 ORDER BY n DESC LIMIT 40", (THEMES[-1][1],))
    except sqlite3.OperationalError:
        d["participants"] = []
    d["places"] = rows("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END id, x.name, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='PLACE' ORDER BY l.weight DESC LIMIT 20", (fid, fid, fid, fid))
    _DASH.update(t=time.time(), d=d)
    return d


_INS = {"t": 0, "d": None}


def api_insights(p):
    """LIGHT BULBS: connections that are not obvious from any one page, each with its evidence (cached 10 min):
    surprising pairs (co-mentioned far more than their sizes predict), hidden links (never on a page together, many shared companions),
    bridges (one phone number, address or aircraft shared by several people), cross-source people (named in more than one release),
    figures on lead pages (public figures mentioned on pages that use a lead's words)."""
    if _INS["d"] and time.time() - _INS["t"] < 600 and not p.get("fresh"):
        return _INS["d"]
    out = {"bulbs": []}
    npages = one("SELECT COUNT(*) n FROM pages")["n"] or 1
    top = rows("SELECT id, name, mentions FROM entities WHERE type='PERSON' AND name LIKE '% %' AND name NOT GLOB '*[A-Z][A-Z][A-Z]*' AND name NOT LIKE \"%'s\" "
               "AND lower(name) NOT GLOB '*death*' AND lower(name) NOT GLOB '*investigat*' AND lower(name) NOT GLOB '*report*' AND lower(name) NOT GLOB '*exhibit*' AND lower(name) NOT GLOB '*deposition*' "
               "AND lower(name) NOT GLOB '* sent' AND lower(name) NOT GLOB '* cc' AND lower(name) NOT GLOB '* re' AND lower(name) NOT GLOB '* fw' ORDER BY mentions DESC LIMIT 600")
    lawyers = {r["entity_id"] for r in rows("SELECT entity_id FROM profiles WHERE found=1 AND category='law'")}
    toks = {t["id"]: {w for w in re.sub(r"[^a-z ]", "", t["name"].lower()).split() if len(w) >= 4} for t in top}
    tid = {t["id"]: t for t in top}; ids = ",".join(str(t["id"]) for t in top)
    pcount = {r["entity_id"]: r["n"] for r in rows(f"SELECT entity_id, COUNT(DISTINCT page_id) n FROM mentions WHERE entity_id IN ({ids}) GROUP BY entity_id")}
    adj = collections.defaultdict(dict)
    for r in rows(f"SELECT a, b, weight FROM links WHERE kind='co-page' AND weight>=2 AND a IN ({ids}) AND b IN ({ids})"):
        adj[r["a"]][r["b"]] = r["weight"]; adj[r["b"]][r["a"]] = r["weight"]
    # 1 surprising pairs: lift = shared pages * all pages / (pages of a * pages of b), both with a real footprint
    import math
    sp = []
    for a, nb in adj.items():
        for b, w in nb.items():
            if a < b and w >= 6 and pcount.get(a, 0) >= 20 and pcount.get(b, 0) >= 20 and not (toks[a] & toks[b]):   # a shared surname is the same person or a family, not a surprise
                lift = w * npages / (pcount[a] * pcount[b])
                if lift >= 20:
                    sp.append((w * math.log(lift) * (0.3 if a in lawyers and b in lawyers else 1.0), lift, a, b, w))
    sp.sort(reverse=True)
    kept = 0
    for score, lift, a, b, w in sp[:80]:
        nd = one("SELECT COUNT(DISTINCT m1.doc_id) n FROM mentions m1 JOIN mentions m2 ON m2.page_id=m1.page_id WHERE m1.entity_id=? AND m2.entity_id=?", (a, b))["n"]
        if nd < 3:
            continue                                         # one memo that lists both is not a pattern: at least three documents
        out["bulbs"].append({"kind": "surprising pair", "a": tid[a], "b": tid[b], "why": f"{tid[a]['name']} and {tid[b]['name']} share {w} pages in {nd} documents, {lift:.0f}× more often than their footprints predict ({pcount[a]} and {pcount[b]} pages each)", "weight": w, "score": round(score)})
        kept += 1
        if kept >= 12:
            break
    # 2 hidden links: no page in common, many common companions (weighted by the smaller of the two link weights)
    hl = []
    for a in list(adj)[:300]:
        for b in list(adj)[:300]:
            if a < b and b not in adj[a] and not (toks[a] & toks[b]):
                common = set(adj[a]) & set(adj[b])
                if len(common) >= 6:
                    s = sum(min(adj[a][c], adj[b][c]) for c in common)
                    hl.append((s, len(common), a, b, sorted(common, key=lambda c: -min(adj[a][c], adj[b][c]))[:5]))
    hl.sort(reverse=True)
    for s, n, a, b, via in hl[:12]:
        out["bulbs"].append({"kind": "hidden link", "a": tid[a], "b": tid[b], "via": [tid[c] for c in via], "why": f"{tid[a]['name']} and {tid[b]['name']} never appear on the same page, yet share {n} companions, most of all " + ", ".join(tid[c]["name"] for c in via[:3]), "weight": n, "score": s})
    # 3 bridges: a phone number, address or aircraft that several people share pages with
    for t, label in (("PHONE", "phone number"), ("EMAIL", "e-mail address"), ("TAIL", "aircraft")):
        for r in rows(f"SELECT x.id, x.name, COUNT(*) n FROM links l JOIN entities x ON x.id=l.a JOIN entities y ON y.id=l.b WHERE l.kind='co-page' AND l.weight>=2 AND x.type=? AND y.type='PERSON' AND y.id IN ({ids}) GROUP BY x.id HAVING n>=3 ORDER BY n DESC LIMIT 6", (t,)) +                  rows(f"SELECT x.id, x.name, COUNT(*) n FROM links l JOIN entities x ON x.id=l.b JOIN entities y ON y.id=l.a WHERE l.kind='co-page' AND l.weight>=2 AND x.type=? AND y.type='PERSON' AND y.id IN ({ids}) GROUP BY x.id HAVING n>=3 ORDER BY n DESC LIMIT 6", (t,)):
            people = rows(f"SELECT y.id, y.name, l.weight FROM links l JOIN entities y ON y.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND y.type='PERSON' AND y.id IN ({ids}) ORDER BY l.weight DESC LIMIT 6", (r["id"], r["id"], r["id"]))
            if len(people) >= 3:
                out["bulbs"].append({"kind": "bridge", "a": {"id": r["id"], "name": r["name"], "type": t}, "via": people, "why": f"the {label} {r['name']} shares pages with {len(people)}+ people: " + ", ".join(x["name"] for x in people[:4]), "weight": r["n"], "score": r["n"]})
    seen = set(); out["bulbs"] = [b for b in out["bulbs"] if not (b["kind"] == "bridge" and (b["a"]["id"] in seen or seen.add(b["a"]["id"])))]
    # 4 cross-source people: named in more than one release
    cs = rows(f"SELECT m.entity_id id, COUNT(DISTINCT p.item) items, COUNT(DISTINCT m.doc_id) docs FROM mentions m JOIN pages p ON p.id=m.page_id WHERE m.entity_id IN ({ids}) GROUP BY m.entity_id HAVING items>=3 ORDER BY docs DESC LIMIT 15")
    nitems = one("SELECT COUNT(*) n FROM items")["n"]
    for r in cs:
        out["bulbs"].append({"kind": "across sources", "a": tid[r["id"]], "why": f"{tid[r['id']]['name']} is named in {r['items']} of the {nitems} releases ({r['docs']} documents): a court file, a DOJ data set and a House production each have them", "weight": r["docs"], "score": r["items"] * 10})
    # 5 public figures on lead pages
    figs = {f["id"]: f for f in api_figures({})["figures"][:150]}
    if figs:
        fids = ",".join(map(str, figs))
        for name, q in THEMES[:6]:
            try:
                r2 = rows(f"SELECT m.entity_id id, COUNT(DISTINCT m.page_id) n FROM mentions m WHERE m.entity_id IN ({fids}) AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?) GROUP BY m.entity_id ORDER BY n DESC LIMIT 5", (q,))
            except sqlite3.OperationalError:
                continue
            for x in r2:
                if x["n"] >= 3:
                    f = figs[x["id"]]
                    out["bulbs"].append({"kind": "figure on lead pages", "a": {"id": f["id"], "name": f["name"], "type": "PERSON"}, "lead": name, "q": q, "why": f"{f['name']} ({f['category']}) is mentioned on {x['n']} pages that use the words of the lead '{name}' — read them before drawing anything", "weight": x["n"], "score": x["n"]})
    out["bulbs"].sort(key=lambda b: -b["score"])
    out["note"] = "A pattern in the mentions is not a finding: every one links to the pages it rests on. Read them; the notebook is for what you conclude."
    _INS.update(t=time.time(), d=out)
    return out


def api_money(p):
    mn = float(p.get("min", 0) or 0); mx = float(p.get("max", 0) or 0); who = p.get("who", "").strip().lower(); flag = p.get("flag", ""); verb = p.get("verb", ""); sort = p.get("sort", "amount"); limit = min(int(p.get("limit", 200)), 1000)
    rel = int(p.get("rel", 1)); press = p.get("press", "0") == "1"
    sql = ("SELECT y.id, y.page_id, y.doc_id, y.amount, y.verb, y.payer_id, y.payee_id, y.payer_raw, y.payee_raw, y.flags, y.quote, y.item, p.pdf_page, p.bates, d.docket, a.name payer, b.name payee "
           "FROM payments y JOIN pages p ON p.id=y.page_id JOIN documents d ON d.id=y.doc_id LEFT JOIN entities a ON a.id=y.payer_id LEFT JOIN entities b ON b.id=y.payee_id WHERE 1=1")
    args = []
    sql += " AND y.relevance>=?"; args.append(rel)
    if not press: sql += " AND y.press=0"
    if mn: sql += " AND y.amount>=?"; args.append(mn)
    if mx: sql += " AND y.amount<=?"; args.append(mx)
    if who: sql += " AND (lower(a.name) LIKE ? OR lower(b.name) LIKE ? OR lower(y.payer_raw) LIKE ? OR lower(y.payee_raw) LIKE ? OR lower(y.quote) LIKE ?)"; args += [f"%{who}%"] * 5
    if flag: sql += " AND (',' || y.flags || ',') LIKE ?"; args.append(f"%,{flag},%")
    if verb: sql += " AND y.verb=?"; args.append(verb)
    sql += " ORDER BY " + {"amount": "y.relevance DESC, y.amount DESC", "page": "y.page_id", "flags": "length(y.flags) DESC, y.relevance DESC, y.amount DESC"}.get(sort, "y.amount DESC") + " LIMIT ?"; args.append(limit)
    return {"payments": rows(sql, args), "total": one("SELECT COUNT(*) n FROM payments")["n"], "relevant": one("SELECT COUNT(*) n FROM payments WHERE relevance>=1 AND press=0")["n"]}


def api_money_summary(p):
    out = {"total": one("SELECT COUNT(*) n, ROUND(SUM(amount)) s FROM payments")}
    out["verbs"] = rows("SELECT verb, COUNT(*) n, ROUND(SUM(amount)) s FROM payments GROUP BY verb ORDER BY n DESC")
    out["flags"] = {f: c for f, c in collections.Counter(f for (fs,) in db().execute("SELECT flags FROM payments") for f in fs.split(",") if f).items()}
    out["payers"] = rows("SELECT a.id, a.name, a.type, COUNT(*) n, ROUND(SUM(y.amount)) s FROM payments y JOIN entities a ON a.id=y.payer_id GROUP BY a.id ORDER BY n DESC LIMIT 30")
    out["payees"] = rows("SELECT b.id, b.name, b.type, COUNT(*) n, ROUND(SUM(y.amount)) s FROM payments y JOIN entities b ON b.id=y.payee_id GROUP BY b.id ORDER BY n DESC LIMIT 30")
    out["pairs"] = rows("SELECT a.id a_id, a.name a_name, b.id b_id, b.name b_name, l.weight n, l.docs s FROM links l JOIN entities a ON a.id=l.a JOIN entities b ON b.id=l.b WHERE l.kind='paid' AND length(a.name)>=5 AND length(b.name)>=5 AND a.name NOT GLOB '*[0-9]*' AND b.name NOT GLOB '*[0-9]*' AND l.docs>=100 ORDER BY l.weight DESC, l.docs DESC LIMIT 40")
    out["banks"] = rows("SELECT name, COUNT(*) n, COUNT(DISTINCT doc_id) docs FROM bank_pages GROUP BY lower(name) ORDER BY n DESC LIMIT 25")
    out["biggest"] = rows("SELECT y.id, y.amount, y.verb, y.payer_raw, y.payee_raw, y.flags, y.page_id, p.pdf_page, p.bates, substr(y.quote,1,220) quote FROM payments y JOIN pages p ON p.id=y.page_id WHERE y.relevance=2 AND y.press=0 AND y.amount<1e9 ORDER BY y.amount DESC LIMIT 25")
    out["structuring"] = rows("SELECT y.id, y.amount, y.verb, y.payer_raw, y.payee_raw, y.page_id, p.pdf_page, p.bates, substr(y.quote,1,220) quote FROM payments y JOIN pages p ON p.id=y.page_id WHERE (','||y.flags||',') LIKE '%,structuring,%' AND y.press=0 ORDER BY y.relevance DESC, y.amount DESC LIMIT 40")
    out["statements"] = rows("SELECT p.doc_id, d.docket, d.title, COUNT(*) n, ROUND(SUM(y.amount)) s, MIN(y.page_id) page_id FROM payments y JOIN pages p ON p.id=y.page_id JOIN documents d ON d.id=p.doc_id WHERE y.verb='statement-line' GROUP BY p.doc_id ORDER BY n DESC LIMIT 25")
    out["repeated"] = rows("SELECT y.amount, y.payee_raw, COUNT(*) n, COUNT(DISTINCT y.doc_id) docs, MIN(y.page_id) page_id FROM payments y WHERE y.relevance>=1 AND y.press=0 AND y.amount>=1000 AND y.payee_raw<>'' GROUP BY y.amount, lower(y.payee_raw) HAVING n>=3 ORDER BY n DESC LIMIT 25")
    SECRECY = ("VI", "VG", "KY", "BM", "CH", "LU", "LI", "MC", "BZ", "PA", "AE", "BS", "CY", "SC", "MU", "AG", "BB", "BL", "SX", "AI", "QA", "BH", "SG", "HK")
    out["jurisdictions"] = rows("SELECT g.country, COUNT(DISTINCT y.page_id) pages, COUNT(DISTINCT y.doc_id) docs, ROUND(SUM(y.amount)) s, MAX(e.name) name FROM payments y JOIN mentions m ON m.page_id=y.page_id JOIN geo g ON g.entity_id=m.entity_id JOIN entities e ON e.id=m.entity_id "
                                "WHERE y.relevance>=1 AND y.press=0 AND g.kind IN ('country','city') AND g.country<>'US' GROUP BY g.country ORDER BY pages DESC LIMIT 30")
    for j in out["jurisdictions"]:
        j["secrecy"] = j["country"] in SECRECY
    out["note"] = "An amount is a figure next to a money word on a page: a court filing's claim, an invoice, a statement line, a press figure. Payer and payee are read from the sentence; when it does not say, the raw words are kept and no one is named. Flags are patterns to look at, not findings."
    return out


_GLOBE = {}


def api_globe(p):
    """points = geocoded places / airports / countries with their page counts on the chosen page set; arcs = two located things on the same page
    (a flight leg when both are airports); photos = picture pages of documents that mention the place. The page set: every page, or the pages
    of a focus person, or the pages a lead matches. Cached per query for 10 min."""
    key = json.dumps(sorted(p.items()))
    if key in _GLOBE and time.time() - _GLOBE[key][0] < 600:
        return _GLOBE[key][1]
    focus = p.get("focus"); lead = p.get("lead", ""); kind = p.get("kind", "all"); minw = int(p.get("min", 2)); photos = p.get("photos", "1") == "1"
    kinds = {"all": ("country", "city", "state", "region", "airport"), "places": ("city", "state", "region"), "airports": ("airport",), "countries": ("country",)}.get(kind, ("country", "city", "state", "region", "airport"))
    ksel = ",".join("?" * len(kinds))
    where = ""; args = list(kinds); note = "every page"
    if focus:
        where = " AND m.page_id IN (SELECT page_id FROM mentions WHERE entity_id=?)"; args.append(int(focus)); note = "the pages that mention " + (one("SELECT name FROM entities WHERE id=?", (int(focus),)) or {"name": "?"})["name"]
    elif lead:
        q = next((t[1] for t in THEMES if t[0] == lead), None)
        if q:
            where = " AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?)"; args.append(q); note = "the pages of the lead '" + lead + "'"
    rws = rows(f"SELECT m.page_id, m.entity_id, g.lat, g.lon, g.kind, g.country, e.name FROM mentions m JOIN geo g ON g.entity_id=m.entity_id JOIN entities e ON e.id=m.entity_id WHERE g.kind IN ({ksel}){where}", args)
    pts = {}; perpage = collections.defaultdict(set); alias = {}   # the same spot under several names (United States / U.S / USA) is ONE dot: the biggest name, the pages pooled
    for r in rws:
        spot = (round(r["lat"], 2), round(r["lon"], 2))
        if spot not in alias:
            alias[spot] = r["entity_id"]
        pid_e = alias[spot]
        d = pts.setdefault(pid_e, {"id": pid_e, "name": r["name"], "lat": r["lat"], "lon": r["lon"], "kind": r["kind"], "country": r["country"], "pages": set(), "names": {}})
        d["names"][r["name"]] = d["names"].get(r["name"], 0) + 1
        d["pages"].add(r["page_id"]); perpage[r["page_id"]].add(pid_e)
    arcs = collections.defaultdict(set)
    for pid, es in perpage.items():
        es = sorted(es)
        if len(es) > 25:
            continue
        for i in range(len(es)):
            for j in range(i + 1, len(es)):
                if (pts[es[i]]["lat"], pts[es[i]]["lon"]) != (pts[es[j]]["lat"], pts[es[j]]["lon"]):
                    arcs[(es[i], es[j])].add(pid)
    points = sorted(pts.values(), key=lambda d: -len(d["pages"]))[:400]
    keep = {d["id"] for d in points}
    out_arcs = [{"a": a, "b": b, "w": len(v), "pages": sorted(v)[:5]} for (a, b), v in arcs.items() if len(v) >= minw and a in keep and b in keep]
    out_arcs.sort(key=lambda x: -x["w"]); out_arcs = out_arcs[:600]
    for d in points:
        d["n"] = len(d["pages"]); d["pages"] = sorted(d["pages"])[:6]; d["name"] = max(d["names"], key=d["names"].get); d["aliases"] = sorted(d["names"], key=lambda k: -d["names"][k])[:6]; del d["names"]
    ph = []
    if photos and points:
        ids = ",".join(str(d["id"]) for d in points[:150])
        for r in rows(f"SELECT m.entity_id, p.id page_id, p.pdf_page, p.bates, COUNT(*) OVER (PARTITION BY m.entity_id) n FROM mentions m JOIN pages p ON p.doc_id=m.doc_id AND p.photo=1 WHERE m.entity_id IN ({ids}){where.replace('m.page_id', 'm.page_id')} GROUP BY m.entity_id, p.id ORDER BY m.entity_id LIMIT 4000", args[len(kinds):] if False else ([] + args[len(kinds):])):
            ph.append({"entity_id": r["entity_id"], "page_id": r["page_id"], "pdf_page": r["pdf_page"], "bates": r["bates"]})
    res = {"points": points, "arcs": out_arcs, "photos": ph, "note": note, "kinds": kinds}
    _GLOBE[key] = (time.time(), res)
    return res


def api_flights(p):
    byp = collections.defaultdict(set)
    for r in rows("SELECT m.page_id, g.label FROM mentions m JOIN geo g ON g.entity_id=m.entity_id WHERE g.kind='airport'"):
        byp[r["page_id"]].add(r["label"])
    pids = list(byp)
    if not pids:
        return {"legs": []}
    dates = collections.defaultdict(set)
    for r in rows("SELECT m.page_id, e.name FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='DATE' AND m.page_id IN (%s)" % ",".join(map(str, pids))):
        dates[r["page_id"]].add(r["name"])
    people = collections.defaultdict(collections.Counter)
    for r in rows("SELECT m.page_id, e.name FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='PERSON' AND e.name LIKE '%% %%' AND m.page_id IN (%s)" % ",".join(map(str, pids))):
        people[r["page_id"]][r["name"]] += 1
    out = []
    for pid, aps in byp.items():
        if len(aps) < 2:
            continue
        pg = one("SELECT p.pdf_page, p.bates, d.docket, p.item FROM pages p JOIN documents d ON d.id=p.doc_id WHERE p.id=?", (pid,))
        years = sorted({y for d in dates[pid] for y in re.findall(r"\b(?:19|20)\d\d\b", d)})
        out.append({"page_id": pid, "pdf_page": pg["pdf_page"], "bates": pg["bates"] or pg["docket"], "item": pg["item"], "airports": sorted(aps), "years": years, "dates": sorted(dates[pid])[:6], "people": [n for n, _ in people[pid].most_common(12)]})
    out.sort(key=lambda x: (x["years"][0] if x["years"] else "9999", x["page_id"]))
    return {"legs": out, "note": "Each row is a page that names two or more airports (a flight-record page): the airports, the dates on that page and the people named on it. The pairing of a person with a leg is the page's, not the studio's."}


def api_timeline2(p):
    focus = p.get("focus"); lead = p.get("lead", "")
    where = ""; args = []
    if focus:
        where = " AND m.page_id IN (SELECT page_id FROM mentions WHERE entity_id=?)"; args.append(int(focus))
    elif lead:
        q = next((t[1] for t in THEMES if t[0] == lead), None)
        if q:
            where = " AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?)"; args.append(q)
    years = collections.Counter(); samples = collections.defaultdict(list)
    for r in rows(f"SELECT e.name, m.page_id FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='DATE'{where}", args):
        y = re.search(r"\b(19[5-9]\d|20[0-2]\d)\b", r["name"])
        if y:
            years[int(y.group(1))] += 1
            if len(samples[int(y.group(1))]) < 40 and r["page_id"] not in [s[1] for s in samples[int(y.group(1))]]:
                samples[int(y.group(1))].append((r["name"], r["page_id"]))
    out = [{"year": y, "n": n, "samples": [{"date": d, "page_id": pid} for d, pid in samples[y][:12]]} for y, n in sorted(years.items())]
    return {"years": out, "note": "Pages by the year of the dates they carry (a date on a page is the page's, not an event date): the shape of the record, then the pages behind any year."}


def api_globe_point(p):
    eid = int(p.get("id", 0)); focus = p.get("focus"); lead = p.get("lead", "")
    where = ""; args = [eid]
    if focus:
        where = " AND m.page_id IN (SELECT page_id FROM mentions WHERE entity_id=?)"; args.append(int(focus))
    elif lead:
        q = next((t[1] for t in THEMES if t[0] == lead), None)
        if q:
            where = " AND m.page_id IN (SELECT rowid FROM pages_fts WHERE pages_fts MATCH ?)"; args.append(q)
    e = one("SELECT e.id, e.name, e.type, e.mentions, e.docs, g.kind, g.country FROM entities e JOIN geo g ON g.entity_id=e.id WHERE e.id=?", (eid,))
    people = rows(f"SELECT x.id, x.name, COUNT(DISTINCT m2.page_id) n FROM mentions m JOIN mentions m2 ON m2.page_id=m.page_id JOIN entities x ON x.id=m2.entity_id WHERE m.entity_id=? AND x.type='PERSON' AND x.name LIKE '% %'{where} GROUP BY x.id ORDER BY n DESC LIMIT 30", args)
    pages = rows(f"SELECT DISTINCT m.page_id, p.pdf_page, p.bates, d.docket, m.quote FROM mentions m JOIN pages p ON p.id=m.page_id JOIN documents d ON d.id=p.doc_id WHERE m.entity_id=?{where} ORDER BY m.page_id LIMIT 12", args)
    photos = rows("SELECT DISTINCT p.id page_id, p.pdf_page, p.bates FROM mentions m JOIN pages p ON p.doc_id=m.doc_id AND p.photo=1 WHERE m.entity_id=? ORDER BY p.id LIMIT 24", (eid,))
    return {"place": e, "people": people, "pages": pages, "photos": photos}


_LOOK = {}


def api_lookup(p):
    """a Wikipedia summary for EXACTLY this title (unverified: same-name people exist); fetched on the user's click, cached, never stored in the database"""
    import urllib.request
    name = re.sub(r"\s+", " ", p.get("name", "")).strip()
    if not name or len(name) > 80:
        return {"found": False}
    if name in _LOOK:
        return _LOOK[name]
    try:
        req = urllib.request.Request("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.replace(" ", "_")), headers={"User-Agent": "LionEpsteinFilesStudio/1.0 (local research tool)"})
        d = json.load(urllib.request.urlopen(req, timeout=15))
        same = re.sub(r"[^a-z0-9]", "", (d.get("title") or "").lower()) == re.sub(r"[^a-z0-9]", "", name.lower())   # a redirect to another title is NOT this person (Sarah Kellen -> a relative's page)
        out = {"found": d.get("type") == "standard" and same, "title": d.get("title"), "description": d.get("description"), "extract": (d.get("extract") or "")[:900], "url": (d.get("content_urls") or {}).get("desktop", {}).get("page")}
    except Exception:   # noqa: BLE001  (404 = no such article)
        out = {"found": False}
    _LOOK[name] = out
    return out


def api_notebook(method, p, body):
    if method == "GET":
        return {"entries": rows("SELECT * FROM notebook ORDER BY id DESC")}
    if method == "POST":
        d = json.loads(body or "{}")
        db().execute("INSERT INTO notebook(kind, created, title, body, refs) VALUES(?,?,?,?,?)", (d.get("kind", "note"), time.strftime("%Y-%m-%dT%H:%M:%S"), d.get("title", "")[:200], d.get("body", "")[:20000], json.dumps(d.get("refs", []))[:20000])); db().commit()
        return {"ok": True}
    if method == "DELETE":
        db().execute("DELETE FROM notebook WHERE id=?", (int(p.get("id", 0)),)); db().commit()
        return {"ok": True}
    return {"error": "method"}


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "static"), **k)

    def log_message(self, fmt, *args):   # counts only: never a query's words in the journal
        sys.stderr.write("%s %s %s\n" % (time.strftime("%H:%M:%S"), self.command, self.path.split("?")[0][:60]))

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode(); self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(b)

    def _route(self, method):
        u = urllib.parse.urlsplit(self.path); p = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}; path = u.path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode() if method in ("POST", "PUT") else ""
        try:
            if path == "/api/stats": return self._json(api_stats())
            if path == "/api/search": return self._json(api_search(p))
            if path == "/api/entities": return self._json(api_entities(p))
            if path.startswith("/api/entity/"): return self._json(api_entity(int(path.rsplit("/", 1)[1]), p))
            if path == "/api/graph": return self._json(api_graph(p))
            if path == "/api/path": return self._json(api_path(p))
            if path.startswith("/api/doc/"): return self._json(api_doc(int(path.rsplit("/", 1)[1])))
            if path.startswith("/api/page/"): return self._json(api_page(int(path.rsplit("/", 1)[1])))
            if path == "/api/redactions": return self._json(api_redactions(p))
            if path == "/api/timeline": return self._json(api_timeline(p))
            if path == "/api/notebook": return self._json(api_notebook(method, p, body))
            if path == "/api/lookup": return self._json(api_lookup(p))
            if path == "/api/dashboard": return self._json(api_dashboard(p))
            if path == "/api/insights": return self._json(api_insights(p))
            if path == "/api/globe": return self._json(api_globe(p))
            if path == "/api/money": return self._json(api_money(p))
            if path == "/api/flights": return self._json(api_flights(p))
            if path == "/api/timeline2": return self._json(api_timeline2(p))
            if path == "/api/money/summary": return self._json(api_money_summary(p))
            if path == "/api/globe/point": return self._json(api_globe_point(p))
            if path == "/api/emails": return self._json(api_emails(p))
            if path == "/api/photos": return self._json(api_photos(p))
            if path == "/api/figures": return self._json(api_figures(p))
            if path == "/api/themes": return self._json(api_themes(p))
            m = re.fullmatch(r"/thumb/(\d+)\.png", path)
            if m:
                f, ct = thumb_png(int(m.group(1)))
                if not f: return self._json({"error": "no image for this page"}, 404)
                with open(f, "rb") as fh: b = fh.read()
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "public, max-age=86400"); self.end_headers(); self.wfile.write(b); return
            if path == "/api/documents": return self._json({"documents": rows("SELECT d.*, (SELECT COUNT(DISTINCT entity_id) FROM mentions m WHERE m.doc_id=d.id) entities FROM documents d ORDER BY d.first_page")})
            m = re.fullmatch(r"/page/(\d+)\.png", path)
            if m:
                f, ct = page_png(int(m.group(1)))
                if not f: return self._json({"error": "no image for this page"}, 404)
                with open(f, "rb") as fh: b = fh.read()
                self.send_response(200); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(b))); self.send_header("Cache-Control", "public, max-age=86400"); self.end_headers(); self.wfile.write(b); return
        except Exception as e:   # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {str(e)[:200]}"}, 500)
        if method == "GET":
            if path == "/": self.path = "/index.html"
            return super().do_GET()
        self._json({"error": "not found"}, 404)

    def do_GET(self): self._route("GET")
    def do_POST(self): self._route("POST")
    def do_DELETE(self): self._route("DELETE")


if __name__ == "__main__":
    print(f"{PRODUCT} on http://{HOST}:{PORT} (db {DB})", flush=True)
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
