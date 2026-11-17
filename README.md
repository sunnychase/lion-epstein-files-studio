# The Epstein Files - Lion Studios

(c) 2026 Sunny Chase - Lion Studios. All rights reserved. Proprietary software: see LICENSE.

**A detective's desk for public records: every person, place, date and thing in the Epstein court and government files, every link between them backed by a quoted page, and a case notebook.** One small Python server (standard library + SQLite), any browser.

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

| item | what | pages |
|---|---|---|
| [jeffrey-epstein-files-full](https://archive.org/details/jeffrey-epstein-files-full) (Internet Archive) | Giuffre v. Maxwell, S.D.N.Y. 15-cv-7433: the documents unsealed in January 2024 (ECF 1320 and its exhibits) | 944 |

More items (the DOJ and House releases on the Internet Archive) are added with the same ingester; each keeps its provenance (item, file, PDF page).

## How it works

`ingest.py` reads each PDF with `pdftotext`, finds document boundaries from the court docket headers, runs spaCy (`en_core_web_lg`) plus a few regexes on every page, and writes documents, pages, entities, mentions (entity, page, offset, 280-character quote) and links (co-mention on a page and in a document, with the pages as evidence) into `efiles.db` (SQLite, FTS5). The docket header stamped on every page is masked before extraction so it never becomes evidence. `aliases.json` merges spellings of the same person (the list is short and conservative). `server.py` serves the API and `static/` and renders page images with `pdftoppm` on demand.

## Run it

```
python3 -m venv .venv && . .venv/bin/activate && pip install spacy && python3 -m spacy download en_core_web_lg
python3 ingest.py --db efiles.db --source data/<item> --item <item> --title "…" --url "…"
EFILES_HOST=0.0.0.0 EFILES_PORT=8670 python3 server.py        # or the user unit in systemd/
```

Requirements: Python 3.10+, poppler-utils (`pdftotext`, `pdftoppm`), spaCy with `en_core_web_lg`. The front end vendors d3 v7 (ISC).

## Page images (compressed packs)
The releases carry each image set as numbered zip parts of compressed pages (1300 px tall, greyscale, JPEG q45: about a tenth of the
release scans, every line legible). `./fetch_images.sh <set> data/<item>` downloads, verifies and unpacks a set;
`tools/backfill_images.py` then points each page at its image by Bates number. `tools/compress_images.py` makes the packs
(from a folder of originals, or streamed straight from archive.org so no original touches the disk). Full-resolution originals: archive.org.
