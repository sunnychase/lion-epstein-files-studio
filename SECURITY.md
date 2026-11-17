# Security policy

## Reporting a vulnerability

Please report security problems **privately**, through **Report a vulnerability** in this repository's **Security** tab
(GitHub private vulnerability reporting). Do not open a public issue, and do not post exploit details anywhere public.

Include what is affected, how to reproduce it, what an attacker could do with it, and the commit you tested. Remove personal
paths and addresses from logs before you send them. You will get an acknowledgement, and the fix and its disclosure will be
coordinated with you.

There are no version numbers: fixes go to `main` and are listed in [CHANGELOG.md](CHANGELOG.md).

## What the studio is built for

The Epstein Files is a desk for **one person or a trusted local network**. Please keep these boundaries in mind:

- **No login.** The server listens on `127.0.0.1` by default and has no accounts. Anyone who can reach its port can read every
  page and write to the case notebook. To use it from another device, put it behind an authenticating reverse proxy or tunnel;
  never expose it bare to a network you do not trust.
- **It reads only its own folders.** Page images come from the item's folder under `EFILES_ROOT/data` or from renders cached
  under `EFILES_CACHE`; static files are embedded (Rust) or served only from `static/` (Python). A way to read another file is
  a vulnerability: please report it.
- **The only outbound request** is the optional Wikipedia summary lookup for public figures (`/api/lookup`), with the title taken
  from the entity, not from a free URL. A way to make the server fetch an arbitrary URL is a vulnerability.
- **SQL** is parameterised everywhere; the FTS query is built from the user's words with the operators quoted. A query that breaks
  out of that is a vulnerability.
- **The notebook** is the only writable surface. It takes short text; it is not a file upload.

Reports we especially want: reading files outside the data and cache folders, reaching an upstream URL the code does not intend,
running commands through request data, and requests that make the server use unbounded memory, disk or CPU (a path search or a
graph query that never finishes).
