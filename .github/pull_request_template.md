## What and why

<!-- What does this change, and what problem does it solve? Link the issue: "Fixes #123". -->

## How it was tested

<!-- Only what you actually ran, with the result: which sources were ingested, the view, the browser and device. -->

- [ ] `bash scripts/check.sh` passes
- In a browser: <!-- what you opened and what you saw; or "not run" and why -->
- Rust and Python servers answer the same JSON for the endpoints touched: <!-- or "not touched" -->

## Checklist

- [ ] One focused change.
- [ ] Machine-specific values come from `EFILES_*` settings; new settings have a safe default and a line in `systemd/efiles-web.service`.
- [ ] No personal paths, host names, addresses, keys or e-mail addresses in code, docs, screenshots or commit messages.
- [ ] Redactions stay redacted; no feature proposes who a redacted person is; every link keeps its pages as evidence.
- [ ] A new source has a `SOURCE.txt` and its item in the README table; the black-book items are not added.
- [ ] CHANGELOG.md has a dated entry, and the README is updated if behaviour, settings, sources or requirements changed.
- [ ] Anything not tested is said above.
