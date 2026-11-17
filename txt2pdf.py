#!/usr/bin/env python3
"""txt2pdf.py IN.txt OUT.pdf -- a plain Courier PDF of a text file (no dependencies), so a compiled note can be ingested like a record."""
import sys, textwrap
lines = []
for ln in open(sys.argv[1], encoding="utf-8").read().splitlines():
    lines += textwrap.wrap(ln, 105) or [""]
def esc(s): return s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
pages = [lines[i:i + 60] for i in range(0, len(lines), 60)]; objs = []
def add(o): objs.append(o); return len(objs)
font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"); kids = []
for pg in pages:
    content = "BT /F1 9 Tf 36 770 Td 11 TL " + "".join("(" + esc(l) + ") Tj T* " for l in pg) + "ET"
    c = add("<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)); kids.append(len(objs) + 1)
    add("<< /Type /Page /Parent PAGES /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>" % (c, font))
pages_obj = add("<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
objs = [o.replace("PAGES", "%d 0 R" % pages_obj) for o in objs]; cat = add("<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
out = b"%PDF-1.4\n"; offs = []
for i, o in enumerate(objs, 1):
    offs.append(len(out)); out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode("latin-1")
x = len(out)
out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode() + b"".join(b"%010d 00000 n \n" % o for o in offs) + ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, x)).encode()
open(sys.argv[2], "wb").write(out); print(len(pages), "pages")
