# Changelog

Updates to The Epstein Files - Lion Studios, newest first. The project has no version numbers; each entry is dated.

## 2026-11-17

- **CI** on the current action majors (checkout v7, setup-python v7, setup-node v7) and Node 24; the first run on main passed.

## 2026-11-16 — Public release

- **Repository public** under the Lion Studios Source-Available Licence 1.0 (non-commercial use free with attribution; commercial use
  and published forks by permission; the redactions stay redacted as a licence condition).
- **README** in the Lion Studios layout: badges, feature table with screenshots, sources, requirements, configuration, limits, FAQ,
  roadmap, star history; `docs/GETTING-STARTED.md` walks through fetching every source from archive.org and building the studio on
  a clean machine. Issue and pull-request templates, CI (`scripts/check.sh` + `cargo check`), CONTRIBUTING, SECURITY, NOTICE, AGENTS.
- **Image pack release** `images-house-additional-2025-11-12`: the House 2025-11-12 production's 23,124 page images compressed to
  2.4 GB in two parts with a sha256 manifest; `fetch_images.sh` + `tools/backfill_images.py` put them in the viewer.
- **Globe:** Blue Marble from GIBS's Web Mercator grid (the EPSG:4326 set is not power-of-two: tiles landed a column off and the
  outer ones failed); a readable WebGL 2 check with per-browser advice instead of Cesium's error panel; the vendored fonts loaded from
  a doubled path and fell back silently (fixed).
- **Rust server** (`rust/`): the whole API as one static binary (axum, rusqlite with FTS5, r2d2 pool, rust-embed), answering the
  same JSON as `server.py`; the user unit runs it.
- **Design:** the evidence-room look (paper by day, lamp-dark by night, dark by default), masthead mark and wordmark, Fraunces and
  IBM Plex vendored, grouped navigation (Desk / Explore / Connections / Investigate / Notebook), numbered dashboard sections,
  "Patterns" instead of light bulbs.
- **Corpus:** DOJ data set 11 (517,382 pages) and the Florida FOIA release ingested; 11 items, 349,404 documents, 585,199 pages.
- **Money:** relevance (Epstein / Maxwell page, circle of 300), a press filter for newsletter pages, statement-line parsing for
  ledger pages, dates kept with each amount; a summary of repeated amounts and jurisdictions.
- **Watchlist** source: the builder's compiled note on deaths and open investigations after the releases, labelled as a note.
- **Showcase reel** (59 s, 1080p) with an original score, and the README preview loop.

## 2026-11-16 — Afternoon

- Dashboard (default tab), Patterns (surprising pairs, hidden links, bridges, across sources, figures on lead pages), 3D bubbles,
  e-mails (357,000 printed headers as a table with typed links), photos, public figures (Wikipedia one-liners, exact title only),
  leads (saved theme queries), web links, the globe with flight legs, follow the money, the timeline, the path finder.
- `merge.py`: OCR and spelling variants of one person folded with the rule recorded; `aliases.json` for the hand-kept cases.
- Sources: Giuffre v. Maxwell, DOJ data sets 1-8, the House 2025-11-12 production, the data sets 9-11 subset, the FBI Vault records,
  the flight logs, the birthday book, GX 606.

## 2026-11-16 — Morning

- First build: `ingest.py` (pdftotext, spaCy, regex entities, redaction objects, masked stamps), `server.py` (standard library,
  SQLite FTS5), search, people & things, graph, path finder, documents, page viewer, redactions, case notebook.
