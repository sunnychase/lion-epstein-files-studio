# Getting started: the studio on your own machine

(c) 2026 Sunny Chase - Lion Studios. Source-available licence: see LICENSE.

This page takes you from a clean Linux machine to the studio running on the public Epstein records, fetched straight
from the Internet Archive. Nothing here needs an account: every source is a public archive.org item, and the only
GitHub download (the compressed page images) is optional.

What you end up with:

- `efiles.db`: one SQLite file holding every document, page, person, place, date, e-mail, phone number, aircraft,
  dollar amount and redaction object, each with its quoted mentions and the pages that link it to everything else.
- The studio at `http://<your machine>:8670`: search, people and things, graph, path finder, globe, money, timeline,
  e-mails, photos, patterns and the case notebook.

## 1. What you need

| | minimum | the full corpus (11 items, 585,000 pages) |
|---|---|---|
| OS | Linux (Debian / Ubuntu shown; macOS works with Homebrew) | same |
| CPU / RAM | 4 cores, 8 GB | 16+ cores, 32 GB (spaCy is the slow part) |
| disk | 5 GB (the court files) | ~150 GB sources + 6 GB database + room for image packs |
| time | 20 minutes | about a day of ingest, unattended |

Packages:

```
sudo apt install python3 python3-venv poppler-utils imagemagick unzip curl sqlite3
python3 -m venv .venv && . .venv/bin/activate
pip install spacy && python3 -m spacy download en_core_web_lg
```

`poppler-utils` gives `pdftotext` and `pdftoppm` (text and page renders). `imagemagick` is only needed to make
image packs. The Rust server needs a Rust toolchain (`curl https://sh.rustup.rs -sSf | sh`) and a C compiler for the
bundled SQLite; skip it and run `server.py` if you would rather not build anything.

## 2. Get the code

```
git clone https://github.com/sunnychase/lion-epstein-files-studio.git efiles
cd efiles
mkdir -p data cache
```

`data/` holds the sources (one folder per archive.org item), `cache/` the rendered pages. Both are ignored by git.

## 3. Pull the sources from archive.org

Every source folder follows one rule: `data/<item>/` with a `SOURCE.txt` naming the archive.org item and the date you
fetched it. The studio shows that provenance on every page. Files come from `https://archive.org/download/<item>/<file>`;
an item's file list is at `https://archive.org/download/<item>/<item>_files.xml`.

### The quick start: the court files (5 GB, 20 minutes)

```
mkdir -p data/ia-giuffre-maxwell-1320
echo "item jeffrey-epstein-files-full (archive.org), fetched $(date -Is)" > data/ia-giuffre-maxwell-1320/SOURCE.txt
curl -L -o data/ia-giuffre-maxwell-1320/files.xml https://archive.org/download/jeffrey-epstein-files-full/jeffrey-epstein-files-full_files.xml
grep -o 'name="[^"]*\.pdf"' data/ia-giuffre-maxwell-1320/files.xml | cut -d'"' -f2 | while read -r f; do
  curl -sL --retry 3 -o "data/ia-giuffre-maxwell-1320/$f" "https://archive.org/download/jeffrey-epstein-files-full/$f"
done
```

### The small sources (FBI Vault, flight logs, birthday book, GX 606, the data sets 9-11 subset)

`./fetch_small_sources.sh` fetches all five and ingests them. Read it first: it is the pattern for every per-file item
(fetch the `_files.xml`, pick the files you want, `curl` each one, write `SOURCE.txt`). The "black book" items on
archive.org are deliberately not in it and the studio does not ingest them.

### The big productions

| item on archive.org | what | shape | size |
|---|---|---|---|
| `EFTA_12-23-25` | DOJ Epstein Files Transparency Act data sets 1-8 | zips of `VOLxxxxx/IMAGES/…/EFTA########.pdf`, one PDF per document with a text layer | 14 GB |
| `oversight-committee-additional-epstein-files` | House Oversight additional estate documents, 2025-11-12 | load-file production: `TEXT/` (one .txt per document), `DATA/*.dat`, `IMAGES/` (one jpeg per page) | 1 GB text, 25 GB images |
| `epstein-files-data-set-11` | DOJ data set 11 | `DataSet 11.zip` → `VOL00011/…/*.pdf` (517,000 pages) | 27 GB |
| `doj_epstein_library_foia_florida_202602` | DOJ FOIA release, Florida, 27 redacted parts | `Florida.zip` → PDFs | 20 GB |
| `epstein_library_transparency_act_hr_4405_dataset9_202602` | DOJ data set 9 | `DataSet 9.zip`, page images only (no text layer) | 107 GB |
| `epstein_library_transparency_act_hr_4405_dataset10_202605` | DOJ data set 10 | `DataSet 10.zip`, page images only | 84 GB |
| `doj-jeffrey-epstein-first-production-2025` | House Oversight first production, 2025-09 | 33,295 page images in `IMAGES0NN.zip` parts | 79 GB |

A zip item is one resumable download:

```
mkdir -p data/ia-efta-dataset-11 && cd data/ia-efta-dataset-11
echo "item epstein-files-data-set-11 (archive.org), fetched $(date -Is)" > SOURCE.txt
curl -L --retry 5 -C - -o "DataSet 11.zip" "https://archive.org/download/epstein-files-data-set-11/DataSet%2011.zip"
unzip -q "DataSet 11.zip" && cd ../..
```

For the House 2025-11-12 production take only the text and load files (the images are a separate, optional step, see §7):

```
mkdir -p data/ia-house-oversight-additional-20251112 && cd data/ia-house-oversight-additional-20251112
I=oversight-committee-additional-epstein-files
curl -sL -o files.xml "https://archive.org/download/$I/${I}_files.xml"
grep -o 'name="[^"]*"' files.xml | cut -d'"' -f2 | grep -E '^(TEXT|DATA)/' > todo.txt
xargs -P 8 -d '\n' -I{} sh -c 'mkdir -p "$(dirname "{}")"; [ -s "{}" ] || curl -sL --retry 5 -o "{}" "https://archive.org/download/'"$I"'/$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "{}")"' < todo.txt
echo "item $I (archive.org), fetched $(date -Is)" > SOURCE.txt; cd ../..
```

Image-only items (sets 9, 10, the first production) carry no text. The studio needs OCR for those; that step is not in
this repository yet. Keep them on a large disk (we keep ours on a NAS) until it is.

Internet Archive throughput is modest (10-40 MB/s per stream). Run several files in parallel (`xargs -P 8` above) and
let big zips resume with `-C -`. Be a good neighbour: do not open dozens of streams.

## 4. Build the database

One `ingest.py` run per item. The `--mode` matches the source shape:

| mode | for | document boundary |
|---|---|---|
| `pdf` | court filings, FBI Vault, flight logs, the watchlist | the docket header on each page, else the PDF |
| `pdfdocs` | DOJ data sets 1-8, 11, the Florida FOIA | one PDF = one document, named by its Bates number |
| `production` | House load-file productions | `DATA/*.dat` BegBates / EndBates, text from `TEXT/`, pages at form feeds |

```
. .venv/bin/activate
python3 ingest.py --db efiles.db --mode pdf --source data/ia-giuffre-maxwell-1320 --item ia-giuffre-maxwell-1320 \
  --title "Giuffre v. Maxwell (S.D.N.Y. 15-cv-7433): documents unsealed January 2024" \
  --url https://archive.org/details/jeffrey-epstein-files-full
```

Several items in a row: add `--no-rebuild` to each and rebuild the links once at the end, then run the second-pass
tools in this order:

```
python3 -c "import ingest, sqlite3; db=sqlite3.connect('efiles.db', timeout=120); ingest.rebuild(db)"
python3 merge.py  --db efiles.db          # fold OCR / NER spellings of one person (each merge rule is recorded)
python3 extras.py --db efiles.db          # e-mail headers, web links, photo pages
python3 geo.py    --db efiles.db          # places and airports on the globe (offline gazetteer)
python3 money.py  --db efiles.db          # every dollar amount with its verb, payer and payee
python3 enrich.py --db efiles.db --top 900   # Wikipedia one-liners for public figures (network; optional)
```

A re-run of the same `--item` replaces that item, so you can refresh one source without touching the rest.
Timings on a 20-core ARM box: the court files 3 minutes; data sets 1-8 40 minutes; data set 11 (517,000 pages) 2.5
hours; the second-pass tools 10 minutes together. The full corpus makes a 5.6 GB database.

`ingest.py` masks the docket header, the Bates stamp and "Page i of j" on every page before extraction, so a stamp
never becomes evidence. Redaction labels become objects of their own and are never resolved to a person.

## 5. Run the studio

The Rust server (one static binary, the front end embedded):

```
cd rust && cargo build --release && cd ..
EFILES_ROOT=. EFILES_HOST=0.0.0.0 EFILES_PORT=8670 ./rust/target/release/efiles-server
```

Or the Python reference server, same API and front end:

```
EFILES_HOST=0.0.0.0 EFILES_PORT=8670 python3 server.py
```

Open `http://localhost:8670`. `EFILES_HOST=127.0.0.1` (the default) keeps it to your machine; `0.0.0.0` serves your
LAN. There is no login: put it behind a reverse proxy with authentication before exposing it beyond a trusted network.

To keep it running, copy `systemd/efiles-web.service` to `~/.config/systemd/user/`, edit the paths (it expects the
checkout at `~/efiles`), then:

```
systemctl --user daemon-reload && systemctl --user enable --now efiles-web.service
loginctl enable-linger $USER      # so the user unit survives logout
```

## 6. Page images

The viewer shows the scan beside the text. Where the page has its own image file (the House productions) it serves
that; otherwise it renders the PDF page with `pdftoppm` into `cache/` on first view. Nothing to set up.

## 7. Compressed image packs (optional)

The House 2025-11-12 production's 23,124 page images are 25 GB as released. The release
[`images-house-additional-2025-11-12`](https://github.com/sunnychase/lion-epstein-files-studio/releases/tag/images-house-additional-2025-11-12)
carries them compressed to 2.4 GB (1300 px tall, greyscale, JPEG quality 45: every line legible) as two zip parts
and a sha256 manifest. Fetch, verify, unpack, then point the pages at their images by Bates number:

```
./fetch_images.sh house-additional-2025-11-12 data/ia-house-oversight-additional-20251112
python3 tools/backfill_images.py --db efiles.db --item ia-house-oversight-additional-20251112
```

The server picks them up at once. While this repository is private the plain-curl download in `fetch_images.sh`
needs a token: run `gh release download images-house-additional-2025-11-12 -D data/ia-house-oversight-additional-20251112/.packs`
first and the script will skip the download and go straight to verification.

Make your own pack from any image set, without keeping the originals on disk:

```
python3 tools/compress_images.py from-archive --item oversight-committee-additional-epstein-files --pattern '^IMAGES/' --dst data/<item>
python3 tools/compress_images.py pack --src data/<item>/IMAGES --name <set> --out packs
```

The originals, at full resolution, stay on archive.org; `SOURCE.txt` in each folder tells you which item.

## 8. Adding a source of your own

1. Make `data/<item>/` with a `SOURCE.txt` naming where the files came from.
2. Pick the `--mode` from the table in §4. A plain text file becomes a PDF with `python3 txt2pdf.py in.txt out.pdf` so
   it goes through the same page pipeline (that is how the watchlist page was made).
3. Ingest with `--no-rebuild`, then run the rebuild and the second-pass tools.
4. Restart the server; the dashboard and patterns caches refresh themselves.

The studio keeps the files' redactions redacted, labels the watchlist as a compiled note and not a record, and words
every connection as "shares pages with". Keep those rules when you add a source.
