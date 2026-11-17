#!/usr/bin/env python3
# (c) 2026 Sunny Chase - Lion Studios. Source-available licence (non-commercial use free; see LICENSE). Built by Sunny Chase (https://github.com/sunnychase) with Claude (Anthropic) · The Epstein Files - Lion Studios
"""enrich.py -- PUBLIC FIGURES: for the people who share the most pages with a focus person (default Jeffrey Epstein), look up a Wikipedia
article whose title is EXACTLY the name (a disambiguating suffix like ", Duke of York" is allowed; a redirect to another title is not: same-name
people exist). The article's one-line description sorts the person into a category (politics / government, business / finance / technology,
entertainment / arts, royalty, law, media, science / academia, sport, other). Written to the `profiles` table; the studio's Public figures tab
reads it. A profile is CONTEXT about a public figure, never evidence: the files are the evidence, and a mention is a mention.
  python3 enrich.py --db efiles.db [--focus "Jeffrey Epstein"] [--top 600]
"""
import argparse
import json
import re
import sqlite3
import time
import urllib.parse
import urllib.request

CATS = [("law", r"\b(lawyer|attorney|judge|jurist|prosecutor|barrister|solicitor|legal scholar)\b"), ("royalty", r"\b(prince|princess|duke|duchess|king|queen|royal|monarch|emir|sheikh)\b"),
        ("politics / government", r"\b(politician|president|prime minister|senator|governor|congress|mayor|minister|diplomat|ambassador|secretary of|chancellor|attorney general|official|statesman|first lady|member of parliament|mp\b|legislator|government)\b"),
        ("science / academia", r"\b(scientist|physicist|professor|academic|biologist|mathematician|economist|psychologist|researcher|neuroscientist|computer scientist|cognitive|chemist|geneticist)\b"),
        ("business / finance / technology", r"\b(businessman|businesswoman|businessperson|billionaire|investor|financier|entrepreneur|executive|banker|founder|ceo|chief executive|hedge fund|venture|industrialist|magnate|tycoon|philanthropist|heir|heiress|developer|retail|technology|software|internet)\b"),
        ("entertainment / arts", r"\b(actor|actress|singer|musician|comedian|film|director|producer|model|television|entertainer|artist|rapper|dancer|magician|celebrity|author|novelist|writer|playwright|photographer|fashion designer|designer|socialite)\b"),
        ("media", r"\b(journalist|broadcaster|news anchor|editor|publisher|columnist|reporter|media)\b"),
        ("sport", r"\b(footballer|athlete|player|coach|racing driver|boxer|tennis|golfer|olympic)\b")]


NOT_HUMAN = re.compile(r"\b(novel|film|album|song|band|city|town|village|county|river|beach|island|mountain|company|conglomerate|corporation|firm|organization|organisation|code name|battle|operation|species|genus|ship|aircraft|building|hotel|restaurant|brand|magazine|newspaper|television series|tv series|video game|character|fictional|surname|given name|family name|street|district|airport|university|school|church|museum|festival|award|disease|drug|protein)\b", re.I)


def wiki(name):
    req = urllib.request.Request("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(name.replace(" ", "_")), headers={"User-Agent": "TheEpsteinFiles-LionStudios/1.0 (local research tool)"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=15))
    except Exception:   # noqa: BLE001
        return None
    if d.get("type") != "standard":
        return None
    t = re.sub(r"[^a-z0-9]", "", (d.get("title") or "").lower()); n = re.sub(r"[^a-z0-9]", "", name.lower())
    title = d.get("title") or ""
    if not (t == n or (title.lower().startswith(name.lower() + ",") or title.lower().startswith(name.lower() + " ("))):
        return None
    if NOT_HUMAN.search(d.get("description") or "") or not (d.get("description") or "").strip():
        return None                                           # a novel, a city, a company: not a person
    return {"title": title, "description": d.get("description") or "", "extract": (d.get("extract") or "")[:700], "url": (d.get("content_urls") or {}).get("desktop", {}).get("page")}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); ap.add_argument("--focus", default="Jeffrey Epstein"); ap.add_argument("--top", type=int, default=600)
    a = ap.parse_args()
    db = sqlite3.connect(a.db, timeout=60)
    db.execute("CREATE TABLE IF NOT EXISTS profiles(entity_id INTEGER PRIMARY KEY, title TEXT, description TEXT, extract TEXT, url TEXT, category TEXT, checked TEXT, found INTEGER)")
    f = db.execute("SELECT id FROM entities WHERE type='PERSON' AND norm=?", ("PERSON:" + re.sub(r"[^a-z0-9 ]", "", a.focus.lower()),)).fetchone()
    if not f:
        raise SystemExit("no such focus person")
    fid = f[0]
    cands = db.execute("SELECT x.id, x.name, l.weight FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='PERSON' "
                       "AND x.id<>? AND length(x.name) > 5 AND x.name LIKE '% %' ORDER BY l.weight DESC LIMIT ?", (fid, fid, fid, fid, a.top)).fetchall()
    done = {r[0] for r in db.execute("SELECT entity_id FROM profiles")}
    n_new = n_found = 0
    for eid, name, w in cands:
        if eid in done:
            continue
        if re.search(r"\d|[A-Z]{3,}", name) or name.lower().split()[0] in ("mr", "ms", "mrs", "dr", "judge"):
            db.execute("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?,?,?,0)", (eid, None, None, None, None, None, time.strftime("%F"))); continue
        p = wiki(name); n_new += 1
        if p:
            cat = next((c for c, rx in CATS if re.search(rx, p["description"].lower())), "other")      # the one-line description only: an extract names other people
            db.execute("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?,?,?,1)", (eid, p["title"], p["description"], p["extract"], p["url"], cat, time.strftime("%F"))); n_found += 1
            print(f"  {name:32s} {w:5d} shared pages · {cat:32s} · {p['description'][:60]}", flush=True)
        else:
            db.execute("INSERT OR REPLACE INTO profiles VALUES(?,?,?,?,?,?,?,0)", (eid, None, None, None, None, None, time.strftime("%F")))
        if n_new % 25 == 0:
            db.commit()
        time.sleep(0.15)
    db.commit()
    print(f"done: {len(cands)} candidates, {n_new} looked up, {n_found} public profiles; by category:", dict(db.execute("SELECT category, COUNT(*) FROM profiles WHERE found=1 GROUP BY category").fetchall()))


if __name__ == "__main__":
    main()
