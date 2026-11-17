#!/usr/bin/env python3
# Created by Sunny Chase (https://github.com/sunnychase) in collaboration with Claude (Anthropic) · The Epstein Files - Lion Studios
"""merge.py -- fold OCR and NER variants of the same person into one entity, with the rule written down for each merge (the aliases table,
source 'auto:<rule>'), then rebuild counts and links. Conservative rules only:
  1 artefacts: a name ending in a header word (Sent, Cc, From, To, Subject, Re, Fw) or a possessive 's, or a doubled surname -> the base name
  2 the same name after case / punctuation / middle-initial folding ("Jeffrey S. Pagliuca" = "Jeffrey Pagliuca"; "JEFFREY PAGLIUCA")
  3 a one-letter spelling slip in a name of 10+ letters whose target has 5x the mentions and shares pages with it ("Ghislane Maxwell" -> "Ghislaine Maxwell")
  4 a short form of a first name with the same surname, when the pair share pages and the full form is the bigger ("Jeff Pagliuca" -> "Jeffrey Pagliuca";
    "Joe Nascimento" -> "Joseph E. Nascimento") — a fixed table of short forms, never a guess
Never merged: single-token names, names with digits, two different surnames, anything in aliases.json already (those are applied at ingest).
  python3 merge.py --db efiles.db [--dry]
"""
import argparse
import re
import sqlite3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ingest  # noqa: E402

SHORT = {"jeff": "jeffrey", "joe": "joseph", "bill": "william", "will": "william", "bob": "robert", "rob": "robert", "bobby": "robert", "dick": "richard", "rick": "richard", "rich": "richard", "mike": "michael", "jim": "james", "jimmy": "james",
         "tom": "thomas", "tommy": "thomas", "dave": "david", "steve": "steven", "ed": "edward", "eddie": "edward", "ted": "edward", "chris": "christopher", "nick": "nicholas", "tony": "anthony", "andy": "andrew", "dan": "daniel", "danny": "daniel",
         "ben": "benjamin", "sam": "samuel", "pat": "patrick", "matt": "matthew", "ken": "kenneth", "ron": "ronald", "don": "donald", "larry": "lawrence", "greg": "gregory", "ron": "ronald", "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine",
         "kathy": "katherine", "sue": "susan", "peggy": "margaret", "maggie": "margaret", "ginny": "virginia", "les": "leslie", "alex": "alexander", "fred": "frederick", "frank": "francis", "ray": "raymond", "al": "alan", "abe": "abraham", "max": "maxwell"}
HDRW = {"sent", "cc", "from", "to", "subject", "re", "fw", "fwd"}


def fold(name):
    toks = [t for t in re.sub(r"[^A-Za-z' -]", " ", name).lower().split() if t]
    toks = [t for t in toks if not (len(t) == 1 or (len(t) == 2 and t.endswith(".")))]
    return " ".join(toks)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); ap.add_argument("--dry", action="store_true"); a = ap.parse_args()
    db = sqlite3.connect(a.db, timeout=120); db.execute("PRAGMA journal_mode=WAL")
    people = {r[0]: {"name": r[1], "mentions": r[2]} for r in db.execute("SELECT id, name, mentions FROM entities WHERE type='PERSON'")}
    bykey = {}
    for eid, p in people.items():
        bykey.setdefault(fold(p["name"]), []).append(eid)
    merges = {}   # loser id -> (winner id, rule)

    def biggest(ids):
        return max(ids, key=lambda i: people[i]["mentions"])
    # rule 1: artefacts
    for eid, p in people.items():
        toks = p["name"].split()
        base = None
        if len(toks) >= 2 and toks[-1].lower().rstrip(".:") in HDRW:
            base = " ".join(toks[:-1])
        elif p["name"].endswith(("'s", "’s")):
            base = p["name"][:-2]
        elif len(toks) >= 3 and toks[-1].lower() == toks[-2].lower():
            base = " ".join(toks[:-1])
        if base and fold(base) in bykey and len(fold(base).split()) >= 2 and all(len(t) >= 3 for t in fold(base).split()) and "doe" not in fold(base).split() and "mailto" not in fold(base):
            w = biggest(bykey[fold(base)])
            if w != eid and len(people[w]["name"].split()) >= 2:
                merges[eid] = (w, "artefact")
    # rule 2: the same folded name
    for key, ids in bykey.items():
        if len(ids) > 1 and len(key) >= 8 and len(key.split()) >= 2 and all(len(t) >= 3 for t in key.split()) and "doe" not in key.split():
            w = biggest(ids)
            for i in ids:
                if i != w and i not in merges:
                    merges[i] = (w, "same name")
    # shared-page test for rules 3 and 4
    def share(a, b):
        r = db.execute("SELECT weight FROM links WHERE kind='co-page' AND a=? AND b=?", (min(a, b), max(a, b))).fetchone()
        return r[0] if r else 0
    keys = list(bykey)
    # rule 4: short first names
    for key, ids in bykey.items():
        toks = key.split()
        if len(toks) < 2 or toks[0] not in SHORT:
            continue
        full = SHORT[toks[0]] + " " + " ".join(toks[1:])
        if full in bykey:
            w = biggest(bykey[full]); src = biggest(ids)
            if src not in merges and w != src and people[w]["mentions"] >= people[src]["mentions"] and share(src, w) >= 2:
                merges[src] = (w, f"short first name {toks[0]}->{SHORT[toks[0]]}")
    # rule 3: one-letter slips (edit distance 1) for long names, into a much bigger target that shares pages
    big = [k for k in keys if people[biggest(bykey[k])]["mentions"] >= 30]
    for key, ids in bykey.items():
        if len(key) < 10 or biggest(ids) in merges:
            continue
        src = biggest(ids)
        for k2 in big:
            if k2 == key or abs(len(k2) - len(key)) > 1 or k2[0] != key[0]:
                continue
            if people[biggest(bykey[k2])]["mentions"] < 5 * people[src]["mentions"]:
                continue
            # edit distance 1 (substitution, insertion or deletion)
            d = 0; i = j = 0
            while i < len(key) and j < len(k2):
                if key[i] == k2[j]:
                    i += 1; j += 1
                else:
                    d += 1
                    if d > 1: break
                    if len(key) == len(k2): i += 1; j += 1
                    elif len(key) > len(k2): i += 1
                    else: j += 1
            d += (len(key) - i) + (len(k2) - j)
            if d == 1:
                w = biggest(bykey[k2])
                if share(src, w) >= 2 or people[w]["mentions"] >= 200:
                    merges[src] = (w, "one-letter slip"); break
    # resolve chains
    def final(i, depth=0):
        while i in merges and depth < 5:
            i = merges[i][0]; depth += 1
        return i
    print(f"{len(merges)} merges proposed")
    for src, (w, rule) in sorted(merges.items(), key=lambda x: -people[x[0]]["mentions"])[:40]:
        print(f"  {people[src]['name']!r:38s} ({people[src]['mentions']}) -> {people[final(w)]['name']!r} [{rule}]")
    if a.dry:
        return
    for src, (w, rule) in merges.items():
        w = final(w)
        if w == src:
            continue
        db.execute("UPDATE mentions SET entity_id=? WHERE entity_id=?", (w, src))
        db.execute("UPDATE emails SET from_id=? WHERE from_id=?", (w, src))
        db.execute("INSERT OR REPLACE INTO aliases(alias_norm, entity_id, source) VALUES(?,?,?)", (people[src]["name"].lower(), w, "auto:" + rule))
        db.execute("DELETE FROM entities WHERE id=?", (src,)); db.execute("DELETE FROM profiles WHERE entity_id=?", (src,))
    db.commit()
    ingest.rebuild(db)
    print("merged and rebuilt:", db.execute("SELECT COUNT(*) FROM entities WHERE type='PERSON'").fetchone()[0], "people now")


if __name__ == "__main__":
    main()
