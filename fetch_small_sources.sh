#!/bin/bash
# the small public sources found on archive.org 2026-11-16: FBI Vault records (Phase I, with IA's text PDFs), the DOJ sets 9-11 subset (250 PDFs),
# the flight-log court exhibits, the House "birthday book" release, the Maxwell-trial household manual (GX 606). The "black book" items are NOT taken.
set -u; cd ~/efiles/data; D="https://archive.org/download"
mk(){ mkdir -p "$1"; echo "item $2 (archive.org), fetched $(date -Is): $3" > "$1/SOURCE.txt"; }
mk ia-fbi-vault-epstein jeffrey-epstein-part-22-of-22_20250227_2148 "FBI Records: Jeffrey Epstein (vault.fbi.gov), Parts 01-08, the Internet Archive text PDFs"
for i in 1 2 3 4 5 6 7 8; do f="Jeffrey Epstein Part 0$i of 08_text.pdf"; [ -s "ia-fbi-vault-epstein/$f" ] || curl -sL --retry 3 -o "ia-fbi-vault-epstein/$f" "$D/jeffrey-epstein-part-22-of-22_20250227_2148/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$f")"; done
mk ia-efta-datasets-9-11-subset epstein-doj-datasets-9-11-jan2026 "DOJ Epstein Files Transparency Act data sets 9-11 (released 2026-01-30): the 250-document subset mirrored on archive.org"
curl -sL -o /tmp/ds911.xml "$D/epstein-doj-datasets-9-11-jan2026/epstein-doj-datasets-9-11-jan2026_files.xml"
python3 - <<'PY'
import re, subprocess, os, urllib.parse
names = [n for n in re.findall(r'<file name="([^"]+)"', open("/tmp/ds911.xml").read()) if n.lower().endswith(".pdf") and "_text" not in n]
print("ds9-11 pdfs:", len(names))
for n in names:
    p = os.path.join("ia-efta-datasets-9-11-subset", n); os.makedirs(os.path.dirname(p), exist_ok=True)
    if not os.path.exists(p): subprocess.run(["curl", "-sL", "--retry", "3", "-o", p, "https://archive.org/download/epstein-doj-datasets-9-11-jan2026/" + urllib.parse.quote(n)])
PY
mk ia-flight-logs jeffrey-epstein-flight-logs_202009 "the flight-log court exhibits (Giuffre v. Maxwell) and the 1997-2006 flight manifest records"
[ -s ia-flight-logs/flight-logs.pdf ] || curl -sL --retry 3 -o ia-flight-logs/flight-logs.pdf "$D/jeffrey-epstein-flight-logs_202009/jeffrey-epstein-flight-logs.pdf"
[ -s ia-flight-logs/flight-manifest-1997-2006.pdf ] || curl -sL --retry 3 -o ia-flight-logs/flight-manifest-1997-2006.pdf "$D/jeffreyepsteinflightmanifestrecords19972006_202001/$(python3 -c "import urllib.parse; print(urllib.parse.quote('Jeffrey Epstein Flight Manifest Records 1997 - 2006.pdf'))")"
mk ia-house-birthday-book epstein-birthday-book "the 50th-birthday book released by the House Oversight Committee (Request No. 1), Internet Archive text PDF"
[ -s ia-house-birthday-book/birthday-book_text.pdf ] || curl -sL --retry 3 -o ia-house-birthday-book/birthday-book_text.pdf "$D/epstein-birthday-book/$(python3 -c "import urllib.parse; print(urllib.parse.quote('Request No. 1_text.pdf'))")"
mk ia-gx606-household-manual gx-606 "Government Exhibit 606, U.S. v. Maxwell: the Palm Beach household manual"
[ -s ia-gx606-household-manual/gx-606.pdf ] || curl -sL --retry 3 -o ia-gx606-household-manual/gx-606.pdf "$D/gx-606/gx-606.pdf"
du -sh ia-fbi-vault-epstein ia-efta-datasets-9-11-subset ia-flight-logs ia-house-birthday-book ia-gx606-household-manual
for d in ia-fbi-vault-epstein ia-flight-logs ia-house-birthday-book ia-gx606-household-manual; do for f in "$d"/*.pdf; do echo "$f: $(pdfinfo "$f" 2>/dev/null | grep ^Pages | tr -s ' ') $(pdftotext -l 2 "$f" - 2>/dev/null | tr -s '[:space:]' ' ' | cut -c1-80)"; done; done
cd ~/efiles && . .venv/bin/activate
python3 ingest.py --db efiles.db --mode pdf --source data/ia-fbi-vault-epstein --item ia-fbi-vault-epstein --title "FBI Records: Jeffrey Epstein (FBI Vault, Phase I, Parts 1-8)" --url https://archive.org/details/jeffrey-epstein-part-22-of-22_20250227_2148 --no-rebuild 2>&1 | tail -1
python3 ingest.py --db efiles.db --mode pdfdocs --source data/ia-efta-datasets-9-11-subset --item ia-efta-datasets-9-11-subset --title "DOJ Epstein Files Transparency Act data sets 9-11 (2026-01-30): the 250-document subset on archive.org" --url https://archive.org/details/epstein-doj-datasets-9-11-jan2026 --no-rebuild 2>&1 | tail -1
python3 ingest.py --db efiles.db --mode pdf --source data/ia-flight-logs --item ia-flight-logs --title "Flight logs: the Giuffre v. Maxwell exhibit and the 1997-2006 flight manifest records" --url https://archive.org/details/jeffrey-epstein-flight-logs_202009 --no-rebuild 2>&1 | tail -1
python3 ingest.py --db efiles.db --mode pdf --source data/ia-house-birthday-book --item ia-house-birthday-book --title "The 50th-birthday book (House Oversight Committee release, Request No. 1)" --url https://archive.org/details/epstein-birthday-book --no-rebuild 2>&1 | tail -1
python3 ingest.py --db efiles.db --mode pdf --source data/ia-gx606-household-manual --item ia-gx606-household-manual --title "GX 606, U.S. v. Maxwell: the Palm Beach household manual" --url https://archive.org/details/gx-606 --no-rebuild 2>&1 | tail -1
python3 -c "import ingest, sqlite3; db=sqlite3.connect('efiles.db', timeout=120); ingest.rebuild(db); print('links', db.execute('SELECT COUNT(*) FROM links').fetchone()[0])"
python3 merge.py --db efiles.db 2>&1 | tail -1
python3 extras.py --db efiles.db 2>&1 | tail -1
python3 geo.py --db efiles.db 2>&1 | tail -1
python3 enrich.py --db efiles.db --top 900 2>&1 | tail -1
systemctl --user restart efiles-web.service; sleep 2; curl -s http://127.0.0.1:8670/api/stats | python3 -c "import json,sys; d=json.load(sys.stdin); print('STATS', d['documents'], 'docs', d['pages'], 'pages', d['mentions'], 'mentions', d['entities'].get('PERSON'), 'people', len(d['items']), 'items')"
