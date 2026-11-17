#!/bin/bash
# check.sh -- the checks CI runs: py | js | rust | hygiene (no argument: all but rust unless cargo is installed)
set -u; cd "$(dirname "$0")/.."; rc=0
py(){ for f in *.py tools/*.py; do python3 -m py_compile "$f" || rc=1; done; echo "py: $(ls *.py tools/*.py | wc -l) files compile"; }
js(){ for f in static/*.js; do node --check "$f" || rc=1; done
      python3 - <<'PY' || rc=1
import re, subprocess, sys, tempfile
h = open("static/index.html").read(); n = 0
for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", h, re.S):
    n += 1; f = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False); f.write(m.group(1)); f.close()
    r = subprocess.run(["node", "--check", f.name]); sys.exit(r.returncode) if r.returncode else None
print("js: inline scripts", n, "ok")
PY
      echo "js: static/*.js ok"; }
rust(){ if command -v cargo >/dev/null; then (cd rust && cargo check --locked -q) && echo "rust: cargo check ok" || rc=1; else echo "rust: cargo not installed, skipped"; fi; }
hygiene(){ bad=0
  files=$(git ls-files | grep -vE '^static/vendor/|^static/fonts/|\.(png|jpg|webp|gif|mp4|woff2)$')
  grep -nE '/home/[a-z]|/Users/[A-Za-z]' $files | grep -v 'scripts/check.sh' && bad=1
  grep -nE '\b192\.168\.[0-9]+\.[0-9]+|\b10\.[0-9]+\.[0-9]+\.[0-9]+|\b172\.(1[6-9]|2[0-9]|3[01])\.[0-9]+\.[0-9]+' $files | grep -v 'scripts/check.sh' && bad=1
  grep -nE '\b(gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})' $files | grep -v 'scripts/check.sh' && bad=1
  git ls-files | grep -E '(^|/)(keys\.env|\.env|.*\.pem|id_rsa.*|.*\.key)$' && bad=1
  [ $bad = 0 ] && echo "hygiene: clean" || { echo "hygiene: FAIL (above)"; rc=1; }; }
case "${1:-all}" in py) py;; js) js;; rust) rust;; hygiene) hygiene;; all) py; js; rust; hygiene;; *) echo "usage: $0 [py|js|rust|hygiene]"; exit 2;; esac
exit $rc
