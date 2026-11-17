# The Epstein Files - Lion Studios

(c) 2026 Sunny Chase - Lion Studios. All rights reserved. Proprietary software: see LICENSE.

<p align="center"><a href="samples/video/the-epstein-files-reel-59s.mp4"><img src="docs/media/preview.webp" width="100%" alt="The Epstein Files - Lion Studios: the dashboard, 3D bubbles, a real globe of places and flight legs, follow the money, every link backed by a quoted page"></a><br>
<sub>▶ <a href="samples/video/the-epstein-files-reel-59s.mp4"><b>Watch the 59-second showcase reel</b></a> (MP4, 1080p, with an original score): dashboard, timeline, 3D bubbles, a real Earth, follow the money, the graph and the leads. Recorded from the live studio; public records only.</sub></p>



**A detective's desk for public records: every person, place, date and thing in the Epstein court and government files, every link between them backed by a quoted page, and a case notebook.** One static Rust binary over SQLite (a Python reference server is kept beside it), any browser.

*Created by [Sunny Chase](https://github.com/sunnychase) in collaboration with Claude (Anthropic).*

## What it does

- **Search** every page with full-text search (phrases, AND / OR / NOT, NEAR), each hit listing who and what is on that page.
- **People & things**: people, organisations, places, dates, e-mail addresses, phone numbers, aircraft and case numbers, each with its documents, every mention quoted with its page, who and what shares pages with it, and the dates on those pages.
- **Graph**: the connection graph around anyone, node size by mentions, edge width by pages shared; double-click to re-centre.
- **Path finder**: the chain of shared pages between any two things, with the quotes that make each hop.
- **Documents** and the **page viewer**: the scan image beside the text, every recognised name highlighted, previous / next page.
- **Redactions**: every redaction label (Doe 3, [REDACTED], a black block …) as an object of its own with its documents and the named context around it.
- **Case notebook**: pin pages and quotes, keep leads, notes and open questions; export is the SQLite table.

## What it will not do

The redactions in these files protect victims and parties a court withheld. The studio keeps them redacted: it shows where a redaction is and what surrounds it, and it never proposes who a redacted person is. A name on a page is a mention, nothing more; the wording everywhere is "shares pages with", not "linked to".

## Sources

Eleven public items from the Internet Archive, 349,000 documents and 585,000 pages. Each keeps its provenance (item, file, PDF page) and the studio shows it on every page.

| item | what | pages |
|---|---|---|
| [jeffrey-epstein-files-full](https://archive.org/details/jeffrey-epstein-files-full) | Giuffre v. Maxwell, S.D.N.Y. 15-cv-7433: the documents unsealed in January 2024 | 944 |
| [EFTA_12-23-25](https://archive.org/details/EFTA_12-23-25) | DOJ Epstein Files Transparency Act data sets 1-8 | 39,002 |
| [epstein-files-data-set-11](https://archive.org/details/epstein-files-data-set-11) | DOJ data set 11 | 517,382 |
| [doj_epstein_library_foia_florida_202602](https://archive.org/details/doj_epstein_library_foia_florida_202602) | DOJ FOIA release, Florida, 27 redacted parts | 2,931 |
| [oversight-committee-additional-epstein-files](https://archive.org/details/oversight-committee-additional-epstein-files) | House Oversight additional estate documents, 2025-11-12 | 23,109 |
| [epstein-doj-datasets-9-11-jan2026](https://archive.org/details/epstein-doj-datasets-9-11-jan2026) | the 250-document subset of data sets 9-11 | 1,125 |
| [jeffrey-epstein-part-22-of-22_20250227_2148](https://archive.org/details/jeffrey-epstein-part-22-of-22_20250227_2148) | FBI Vault records, Phase I, parts 1-8 | 289 |
| [jeffrey-epstein-flight-logs_202009](https://archive.org/details/jeffrey-epstein-flight-logs_202009) | the flight-log exhibits and the 1997-2006 manifest records | 119 |
| [epstein-birthday-book](https://archive.org/details/epstein-birthday-book) | the 50th-birthday book (House Oversight, Request No. 1) | 238 |
| [gx-606](https://archive.org/details/gx-606) | GX 606, U.S. v. Maxwell: the Palm Beach household manual | 59 |
| watchlist | the builder's compiled watchlist of deaths and open investigations after the releases (press and official statements; not a record) | 1 |

The image-only releases (DOJ data sets 9 and 10, the House first production) are fetched by `nas_fetch_images.sh` and await OCR. **[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md) walks through fetching every source from archive.org and building the studio on your own machine.**

## How it works

`ingest.py` reads each PDF with `pdftotext`, finds document boundaries from the court docket headers, runs spaCy (`en_core_web_lg`) plus a few regexes on every page, and writes documents, pages, entities, mentions (entity, page, offset, 280-character quote) and links (co-mention on a page and in a document, with the pages as evidence) into `efiles.db` (SQLite, FTS5). The docket header stamped on every page is masked before extraction so it never becomes evidence. `aliases.json` merges spellings of the same person (the list is short and conservative). The server (`rust/`, or the Python reference `server.py`) serves the API and `static/` and renders page images with `pdftoppm` on demand.

## Run it

Short form (the full walk-through, from a clean machine to the whole corpus, is [docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)):

```
sudo apt install python3 python3-venv poppler-utils imagemagick unzip curl
python3 -m venv .venv && . .venv/bin/activate && pip install spacy && python3 -m spacy download en_core_web_lg
python3 ingest.py --db efiles.db --mode pdf --source data/<item> --item <item> --title "..." --url "..."
python3 merge.py --db efiles.db && python3 extras.py --db efiles.db && python3 geo.py --db efiles.db && python3 money.py --db efiles.db
cd rust && cargo build --release && cd .. && EFILES_ROOT=. EFILES_HOST=0.0.0.0 ./rust/target/release/efiles-server
```

Requirements: Python 3.10+, poppler-utils (`pdftotext`, `pdftoppm`), spaCy with `en_core_web_lg`; Rust 1.80+ for the binary (or run `python3 server.py`, same API). The front end vendors d3 v7 (ISC), 3d-force-graph (MIT) and CesiumJS (Apache-2.0).

## Page images (compressed packs)
The releases carry each image set as numbered zip parts of compressed pages (1300 px tall, greyscale, JPEG q45: about a tenth of the
release scans, every line legible). `./fetch_images.sh <set> data/<item>` downloads, verifies and unpacks a set;
`tools/backfill_images.py` then points each page at its image by Bates number. `tools/compress_images.py` makes the packs
(from a folder of originals, or streamed straight from archive.org so no original touches the disk). Full-resolution originals: archive.org.

## The server in Rust
`rust/` holds the same server as one static binary (axum + bundled SQLite with FTS5; the front end is embedded at build time):
```
cd rust && cargo build --release          # Rust 1.80+; a C compiler for the bundled SQLite
EFILES_ROOT=.. EFILES_HOST=0.0.0.0 ./target/release/efiles-server
```
Every endpoint answers with the same JSON as `server.py`, so `static/` is shared; `systemd/efiles-web.service` runs the binary.
`server.py` stays as the reference implementation and the fallback. The ingest pipeline (`ingest.py` and friends) remains Python: it leans on spaCy.
