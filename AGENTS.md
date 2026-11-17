# Notes for coding agents

Guidance for AI coding agents (and people) changing this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md) too.

## What this is

An investigator's desk over public records: an ingest pipeline (Python, spaCy) that turns PDFs and productions into one SQLite
file of documents, pages, entities, quoted mentions and page-backed links, and a server (Rust, with a Python reference) that serves
the page and the API. See [How it works](README.md#how-it-works).

## Layout

| path | what it is |
|---|---|
| `rust/src/main.rs` | router, embedded static files, page and thumbnail routes, settings (`EFILES_*`) |
| `rust/src/api.rs` | every endpoint; `PRODUCT` and `COPYRIGHT`; caches for dashboard / patterns / globe / lookup |
| `rust/src/db.rs` | the SQLite pool and the `rows` / `one` / `count` helpers; `args!` macro |
| `server.py` | the same API in plain Python; the reference the Rust port is checked against |
| `ingest.py` | sources -> documents, pages, entities, mentions, links; three modes (`pdf`, `pdfdocs`, `production`); masks stamps; redaction objects |
| `merge.py`, `extras.py`, `geo.py`, `money.py`, `enrich.py` | the second pass: name variants, e-mails / links / photos, the globe, the money, public figures |
| `aliases.json`, `email_owners.json`, `suppressed.json` | hand-kept lists; change them with a reason in the commit |
| `static/index.html`, `static/app.css`, `static/globe.js` | the page, its styles, the CesiumJS globe |
| `static/vendor/`, `static/fonts/` | third-party, unmodified; do not edit |
| `tools/` | image packs (`compress_images.py`, `backfill_images.py`), the reel recorder and its score |
| `fetch_images.sh`, `fetch_small_sources.sh`, `nas_fetch_images.sh`, `txt2pdf.py` | fetching sources and packs |
| `scripts/check.sh` | the CI checks |

## Rules

1. **Config indirection.** Ports, addresses and paths come from `EFILES_*` variables. Never hard-code a machine's values.
2. **Nothing machine-specific or personal** in code, comments, docs, screenshots or commit messages.
3. **Redactions stay redacted.** No feature may propose, infer, rank or hint at who a redacted party is. Do not add a "candidates
   for Doe N" view, a redaction-to-person join, or a prompt that asks a model to guess.
4. **Every link keeps its pages.** A row in `links` carries its evidence pages; a new kind of link (typed relation, e-mailed) does
   too. The UI says "shares pages with"; patterns are routes to quotes, not findings.
5. **Two servers, one API.** A change to an endpoint lands in `server.py` and `rust/src/api.rs` with the same JSON shape, or the
   Python one first with an issue for the port. Compare with `curl` on both.
6. **Sources are public records with provenance.** A new item has a `SOURCE.txt`; the ingester keeps item, file and PDF page for
   every page. The black-book items are not ingested. The watchlist is a note, labelled as such.
7. **Honest data.** Wikipedia is matched on the exact title and is context; e-mail addresses map to people only through
   `email_owners.json`; money flags are patterns. Say "estimate" where it is one.
8. **Match the existing style**: compact functions, short comments that say why, plain words in the UI, no emoji. Element ids in
   `index.html` are used by the scripts; do not rename them casually.
9. **Document changes**: a dated [CHANGELOG.md](CHANGELOG.md) entry; README updates when behaviour, settings, sources or
   requirements change.

## Checks

```bash
bash scripts/check.sh      # py_compile, node --check on the page scripts, cargo check if cargo is present, hygiene grep
```

## Do not

- Commit `efiles.db`, `data/`, `cache/`, `.venv/`, `rust/target/` or `__pycache__/`.
- Make the server listen beyond `127.0.0.1` by default.
- Ingest, download or delete sources, or restart services, as a side effect of a code change.
- Store page text, names from the records or notebook content anywhere outside the database.
