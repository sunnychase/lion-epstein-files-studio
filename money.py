#!/usr/bin/env python3
# (c) 2026 Sunny Chase - Lion Studios. All rights reserved. Proprietary. Built by Sunny Chase (https://github.com/sunnychase) with Claude (Anthropic) · The Epstein Files - Lion Studios
"""money.py -- FOLLOW THE MONEY: every money amount on every page, read with the sentence around it.
  * amount: $ / US$ / USD figures (with million / billion / k scales) and "N dollars"; the numeric value is kept
  * the verb near it decides the kind: paid / wired / transferred / received / deposited / withdrew / check / invoice / loan / fee / retainer /
    settlement / donation / gift / cash / purchase / salary
  * payer and payee: the PERSON / ORG mentions on the same page whose span lies in the sentence window: the one after "to" (or "payable to",
    "in favor of") is the payee, the one after "from" (or before the verb) is the payer; when the sentence does not say, the record keeps the raw
    words and no id
  * flags: structuring (9,000 to 9,999.99 — just under the $10,000 reporting line), round-large (a round amount of $100,000 or more),
    to-individual (the payee is a person), cash (the word cash in the sentence), foreign (a located non-US place on the page), big (≥ $1 million)
  * banks: ORG mentions that name a bank, counted per page
Writes the `payments` table and 'paid' links (payer → payee: count, sum), rebuilt on every run. Grounded: every row has its page and quote.
  python3 money.py --db efiles.db
"""
import argparse
import collections
import json
import re
import sqlite3
import time

AMOUNT = re.compile(r"(?:US\$|USD\s?|\$)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(million|billion|thousand|mm|m|k)?\b|\b(\d{1,3}(?:,\d{3})+|\d{3,})\s(?:U\.?S\.? )?dollars\b", re.I)
VERBS = [("wire", r"\bwire[sd]?\b|\bwire transfer"), ("transfer", r"\btransfer(?:red|s)?\b"), ("paid", r"\bpaid\b|\bpays?\b|\bpayment[s]?\b|\bpayable\b"), ("received", r"\breceived?\b|\breceipt\b"),
         ("deposit", r"\bdeposit(?:ed|s)?\b"), ("withdrawal", r"\bwithdr(?:ew|awal|awn)\b"), ("check", r"\bcheck\b|\bcheque\b|\bcashier'?s check"), ("invoice", r"\binvoice[sd]?\b|\bbill(?:ed)?\b"), ("loan", r"\bloan(?:ed|s)?\b|\blent\b"),
         ("fee", r"\bfees?\b|\bretainer\b|\bcommission\b"), ("settlement", r"\bsettle(?:ment|d)\b|\bjudgment\b|\bdamages\b"), ("donation", r"\bdonat(?:ed|ion|ions)\b|\bgift(?:ed|s)?\b|\bcontribut(?:ed|ion)\b|\bphilanthrop"),
         ("cash", r"\bcash\b"), ("purchase", r"\bpurchase[sd]?\b|\bbought\b|\bsold\b|\bsale\b|\bprice\b"), ("salary", r"\bsalary\b|\bwages?\b|\bcompensation\b|\bbonus\b"), ("trust", r"\btrust\b|\bestate\b|\bfoundation\b|\baccount\b")]
BANK = re.compile(r"\b(JP ?Morgan(?: Chase)?|Chase(?: Bank| Manhattan)?|Deutsche Bank|Bank of America|Citibank|Citigroup|HSBC|Bear Stearns|First Republic|Signature Bank|Bank of New York|BNY Mellon|UBS|Credit Suisse|Goldman Sachs|Morgan Stanley|Wells Fargo|Barclays|Northern Trust|Fidelity|Merrill Lynch|Lehman Brothers|Apollo(?: Global)?|Southern Trust|Bank of Butterfield|Butterfield|Banque|Julius Baer|Pictet|Lombard Odier|BNP Paribas|Societe Generale|Standard Chartered|Royal Bank|TD Bank|PNC|SunTrust|Regions Bank|Capital One|American Express|Amex|Western Union|PayPal)\b", re.I)
TO = re.compile(r"\b(?:to|payable to|in favor of|in favour of|for the benefit of)\s+$", re.I)
FROM = re.compile(r"\b(?:from|by|on behalf of)\s+$", re.I)


def value(m):
    if m.group(3):
        return float(m.group(3).replace(",", ""))
    v = float(m.group(1).replace(",", "")); s = (m.group(2) or "").lower()
    return v * {"million": 1e6, "m": 1e6, "mm": 1e6, "billion": 1e9, "thousand": 1e3, "k": 1e3}.get(s, 1)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--db", required=True); a = ap.parse_args()
    db = sqlite3.connect(a.db, timeout=120); db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    DROP TABLE IF EXISTS payments; DROP TABLE IF EXISTS bank_pages;
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, page_id INTEGER, doc_id INTEGER, amount REAL, verb TEXT, payer_id INTEGER, payee_id INTEGER, payer_raw TEXT, payee_raw TEXT, flags TEXT, quote TEXT, item TEXT, relevance INTEGER DEFAULT 0, press INTEGER DEFAULT 0, date_raw TEXT);
    CREATE INDEX IF NOT EXISTS ix_pay_amt ON payments(amount); CREATE INDEX IF NOT EXISTS ix_pay_payer ON payments(payer_id); CREATE INDEX IF NOT EXISTS ix_pay_payee ON payments(payee_id); CREATE INDEX IF NOT EXISTS ix_pay_page ON payments(page_id);
    CREATE TABLE IF NOT EXISTS bank_pages(entity_id INTEGER, page_id INTEGER, doc_id INTEGER, name TEXT);
    """)
    db.execute("DELETE FROM payments"); db.execute("DELETE FROM bank_pages"); db.execute("DELETE FROM links WHERE kind='paid'")
    foreign_pages = {r[0] for r in db.execute("SELECT DISTINCT m.page_id FROM mentions m JOIN geo g ON g.entity_id=m.entity_id WHERE g.country NOT IN ('US','') AND g.kind IN ('country','city')")}
    # relevance: 2 = Epstein or Maxwell on the page; 1 = one of the 300 people who share the most pages with Epstein; 0 = none (a forwarded article, a brief)
    core = [r[0] for r in db.execute("SELECT id FROM entities WHERE norm IN ('PERSON:jeffrey epstein','PERSON:ghislaine maxwell')")]
    circle = set()
    if core:
        circle = {r[0] for r in db.execute("SELECT CASE WHEN l.a=? THEN l.b ELSE l.a END FROM links l JOIN entities x ON x.id = CASE WHEN l.a=? THEN l.b ELSE l.a END WHERE (l.a=? OR l.b=?) AND l.kind='co-page' AND x.type='PERSON' ORDER BY l.weight DESC LIMIT 300", (core[0], core[0], core[0], core[0]))}
    page_rel = {}
    for pid, eid in db.execute("SELECT page_id, entity_id FROM mentions WHERE entity_id IN (%s)" % ",".join(map(str, set(core) | circle))):
        page_rel[pid] = max(page_rel.get(pid, 0), 2 if eid in core else 1)
    url_pages = {r[0] for r in db.execute("SELECT page_id FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE e.type='URL' GROUP BY page_id HAVING COUNT(*)>=2")}
    PRESS = re.compile(r"\b(Reuters|Bloomberg|Forbes|Associated Press|newsletter|subscribe|all rights reserved|Copyright ©|Read full article|Continues on page|Sent from my iPad|smid=|utm_)", re.I)
    DATE = re.compile(r"\b(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])/(?:\d{2}|\d{4})\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.? \d{1,2},? \d{4}\b")
    paid = collections.defaultdict(lambda: [0, 0.0, set()]); n = 0; t0 = time.time(); nb = 0
    cur = db.execute("SELECT id, doc_id, item, text FROM pages WHERE text LIKE '%$%' OR text LIKE '%dollar%' OR text LIKE '%USD%'")
    for pid, did, item, text in cur.fetchall():
        ments = db.execute("SELECT m.entity_id, e.type, e.name, m.start, m.end FROM mentions m JOIN entities e ON e.id=m.entity_id WHERE m.page_id=? AND e.type IN ('PERSON','ORG')", (pid,)).fetchall()
        for mm in BANK.finditer(text):
            db.execute("INSERT INTO bank_pages(entity_id, page_id, doc_id, name) VALUES(?,?,?,?)", (None, pid, did, mm.group(1))); nb += 1
        amts = list(AMOUNT.finditer(text)); dates = list(DATE.finditer(text))
        huge = sum(1 for m in amts if value(m) >= 1e9)
        rel = page_rel.get(pid, 0); press = 1 if (pid in url_pages or PRESS.search(text) or huge >= 2 or re.search(r"\b(magazine|columnist|reporter|wrote in|according to|told [A-Z][a-z]+ magazine|Vanity Fair|New York Post|Daily Mail|Miami Herald|Wall Street Journal|Financial Times)\b", text)) else 0
        # a statement / ledger page: many amounts and dates -> every line with a date and an amount is a line of it (description = the rest of the line)
        if len(amts) >= 6 and len(dates) >= 3:
            for ln in text.splitlines():
                am = AMOUNT.search(ln); dm = DATE.search(ln)
                if am and dm:
                    v = value(am)
                    if 100 <= v <= 5e11:
                        desc = re.sub(r"\s+", " ", ln.replace(am.group(0), " ").replace(dm.group(0), " ")).strip(" .:-|")[:160]
                        flags = [f for f, ok in (("structuring", 9000 <= v < 10000), ("round-large", v >= 100000 and v % 10000 == 0), ("big", v >= 1e6), ("cash", "cash" in ln.lower()), ("foreign", pid in foreign_pages), ("statement", True)) if ok]
                        db.execute("INSERT INTO payments(page_id, doc_id, amount, verb, payer_id, payee_id, payer_raw, payee_raw, flags, quote, item, relevance, press, date_raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   (pid, did, v, "statement-line", None, None, "", desc, ",".join(flags), re.sub(r"\s+", " ", ln).strip()[:400], item, rel, press, dm.group(0))); n += 1
            continue
        seen = set()
        for m in amts:
            amt = value(m)
            if amt < 100 or amt > 5e11:
                continue
            s, e = m.start(), m.end()
            if (s // 40) in seen:
                continue
            seen.add(s // 40)
            ws, we = max(0, s - 220), min(len(text), e + 220)
            win = text[ws:we]; low = win.lower()
            verb = next((v for v, rx in VERBS if re.search(rx, low)), None)
            if verb is None:
                continue                                     # a bare figure (a page number, a date) is not a payment
            # the parties: mentions inside the window, in order; the one after "to" is the payee, after "from" the payer
            inside = sorted([(st, en, eid, typ, nm) for eid, typ, nm, st, en in ments if st >= ws and en <= we], key=lambda x: x[0])
            payer = payee = None; payer_raw = payee_raw = ""
            for st, en, eid, typ, nm in inside:
                before = text[max(ws, st - 24):st]
                if TO.search(before) and payee is None:
                    payee, payee_raw = eid, nm
                elif FROM.search(before) and payer is None:
                    payer, payer_raw = eid, nm
            if payer is None and inside:                      # the first party before the amount, when none is marked
                cand = [x for x in inside if x[1] <= s]
                if cand and cand[-1][2] != payee:
                    payer, payer_raw = cand[-1][2], cand[-1][4]
            flags = []
            if 9000 <= amt < 10000: flags.append("structuring")
            if amt >= 100000 and amt % 10000 == 0: flags.append("round-large")
            if amt >= 1e6: flags.append("big")
            if "cash" in low: flags.append("cash")
            if pid in foreign_pages: flags.append("foreign")
            if payee is not None and any(x[2] == payee and x[3] == "PERSON" for x in inside): flags.append("to-individual")
            quote = re.sub(r"\s+", " ", win).strip(); dm = DATE.search(win)
            db.execute("INSERT INTO payments(page_id, doc_id, amount, verb, payer_id, payee_id, payer_raw, payee_raw, flags, quote, item, relevance, press, date_raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (pid, did, amt, verb, payer, payee, payer_raw, payee_raw, ",".join(flags), quote[:600], item, rel, press, dm.group(0) if dm else "")); n += 1
            if payer is not None and payee is not None and payer != payee and rel and not press:
                k = (payer, payee); paid[k][0] += 1; paid[k][1] += amt; paid[k][2].add(pid)
    db.executemany("INSERT OR REPLACE INTO links(a, b, kind, weight, pages, docs) VALUES(?,?,?,?,?,?)", [(k[0], k[1], "paid", v[0], json.dumps(sorted(v[2])[:200]), round(v[1])) for k, v in paid.items()])
    db.commit()
    fl = collections.Counter(f for (fs,) in db.execute("SELECT flags FROM payments") for f in fs.split(",") if f)
    rl = dict(db.execute("SELECT relevance, COUNT(*) FROM payments GROUP BY relevance").fetchall()); pr = db.execute("SELECT COUNT(*) FROM payments WHERE press=1").fetchone()[0]
    print(f"done: {n} amounts with a money verb, {len(paid)} payer->payee pairs (Epstein-circle pages, not press), {nb} bank mentions; relevance {rl}, press {pr}; flags {dict(fl)} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
