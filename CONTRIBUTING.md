# Contributing to The Epstein Files - Lion Studios

Thanks for helping. Bug reports, fixes, new public sources, documentation and focused features are all welcome.

## Before you start

- **Bugs and ideas:** open an [issue](https://github.com/sunnychase/lion-epstein-files-studio/issues) with the bug or feature
  form. Search first; one problem or idea per issue.
- **Security problems:** do not open a public issue; see [SECURITY.md](SECURITY.md).
- **Bigger changes** (a new source shape, a change to the schema or to the links, a new view): open an issue first so the
  approach can be agreed before you spend time on it.

## Running it locally

```bash
EFILES_PORT=8671 EFILES_ROOT=. python3 server.py            # a development copy on the Python server
cd rust && cargo build --release && cd .. && EFILES_PORT=8671 EFILES_ROOT=. ./rust/target/release/efiles-server
```

Files under `static/` are read on every request by the Python server, so page changes show on reload. The Rust binary embeds
`static/` at build time: rebuild after a page change. A small database to develop against is the court files alone (20 minutes,
see the README's quick start); `--no-rebuild` lets you ingest several items and rebuild the links once.

## House rules

- **Machine settings live in the environment** (`EFILES_*`). Paths, ports and addresses never go into the code; a new setting
  gets a safe default in both servers and a line in `systemd/efiles-web.service`.
- **No personal or machine-specific data**: no home-directory paths, host names, private addresses, user names, tokens or
  e-mail addresses, in code, docs, comments, screenshots or commit messages.
- **Redactions stay redacted.** No feature may propose, infer or rank who a redacted party is. Redaction labels are objects with
  their documents and context, nothing more.
- **Every link keeps its pages.** Nothing exists without a mention; no link without the pages behind it; the wording is "shares
  pages with". A pattern (lift, bridge, hidden link) is a route to the quotes, not a finding.
- **E-mail addresses map to a person only when documented** (`email_owners.json`); Wikipedia lookups match the exact title and are
  context, never evidence.
- **Two servers, one API.** `server.py` is the reference; `rust/src/api.rs` must answer the same JSON. A new endpoint lands in
  both, or in Python first with an issue for the port.
- **The black-book items are not ingested**, and the compiled watchlist stays labelled as a note, not a record.
- **Say what changed**: a dated entry in [CHANGELOG.md](CHANGELOG.md), and README updates when behaviour, settings, sources or
  requirements change. Numbers in docs come from a real run; say on what.

## Checks

Run before every commit. CI (`.github/workflows/ci.yml`) runs the same script on every push and pull request, plus `cargo check`:

```bash
bash scripts/check.sh            # or one part: py | js | rust | hygiene
```

It compiles every Python file, runs `node --check` on the page scripts and the inline script, and fails on home-directory paths,
private network addresses, token-shaped strings or a tracked keys file.

## Pull requests

- One focused change per pull request, with a short imperative title ("money: read 'retainer' as a fee").
- Fill in the template: what changed, why, how you tested it, and anything you could not test.
- Do not commit `efiles.db`, `data/`, `cache/`, `.venv/`, `rust/target/` or `__pycache__/`.

By contributing you agree that your contribution is licensed to Sunny Chase - Lion Studios under the
[Lion Studios Source-Available Licence](LICENSE), as its section 1(d) says.
