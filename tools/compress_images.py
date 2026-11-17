#!/usr/bin/env python3
# Created by Sunny Chase (https://github.com/sunnychase) in collaboration with Claude (Anthropic) · Lion Epstein Files Studio
"""compress_images.py -- page images small enough to ship: 1300 px tall, greyscale, JPEG quality 45 (about 117 KB a page, a tenth of
the release scans, every line still legible). Two sources, one output tree that keeps the release's relative paths and file names:

  python3 tools/compress_images.py from-dir  --src /mnt/nas/Epstein/images/house-additional-2025-11-12-images --dst data/<item> [--jobs 16]
  python3 tools/compress_images.py from-archive --item oversight-committee-additional-epstein-files --pattern '^IMAGES/' --dst data/<item>
        (streams each file from archive.org straight through ImageMagick: nothing of the original is written to disk)
  python3 tools/compress_images.py pack --src data/<item>/IMAGES --name house-additional-2025-11-12 --out packs [--part-gb 1.5]
        (numbered zip parts under the GitHub release limit, plus MANIFEST.txt with sha256 of each part; fetch_images.sh reads it)

Needs ImageMagick's `convert`. Existing outputs are skipped, so a run can be resumed.
"""
import argparse, concurrent.futures, hashlib, os, re, subprocess, sys, time, urllib.parse, urllib.request, zipfile

CONVERT = ["-resize", "1300x1300>", "-colorspace", "Gray", "-quality", "45", "-strip"]
IMG = re.compile(r"\.(jpe?g|png|tiff?|bmp|gif)$", re.I)


def out_path(dst, rel):
    return os.path.join(dst, re.sub(r"\.(png|tiff?|bmp|gif)$", ".jpg", rel, flags=re.I))


def convert_file(src, dst_file):
    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
    r = subprocess.run(["convert", src + "[0]", *CONVERT, dst_file + ".part"], capture_output=True)
    if r.returncode == 0 and os.path.getsize(dst_file + ".part") > 0:
        os.replace(dst_file + ".part", dst_file); return True
    try: os.remove(dst_file + ".part")
    except OSError: pass
    return False


def convert_url(url, dst_file):
    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "LionEpsteinFilesStudio/1.0"}), timeout=120) as resp:
                r = subprocess.run(["convert", "-[0]", *CONVERT, dst_file + ".part"], stdin=resp, capture_output=True)
            if r.returncode == 0 and os.path.getsize(dst_file + ".part") > 0:
                os.replace(dst_file + ".part", dst_file); return True
        except Exception:   # noqa: BLE001  (a dropped connection: try again)
            pass
        time.sleep(2 + 3 * attempt)
    try: os.remove(dst_file + ".part")
    except OSError: pass
    return False


def run(jobs, tasks, label):
    t0 = time.time(); ok = bad = 0
    with concurrent.futures.ThreadPoolExecutor(jobs) as ex:
        for res in ex.map(lambda t: t[0](*t[1:]), tasks):
            ok += res; bad += (not res)
            if (ok + bad) % 500 == 0:
                print(f"  {label}: {ok + bad}/{len(tasks)} ({bad} failed) {time.time() - t0:.0f}s", flush=True)
    print(f"done: {label}: {ok} converted, {bad} failed, {time.time() - t0:.0f}s")
    return bad


def from_dir(a):
    tasks = []
    for root, _, files in os.walk(a.src):
        for f in files:
            if IMG.search(f):
                rel = os.path.relpath(os.path.join(root, f), a.src); o = out_path(a.dst, rel)
                if not os.path.exists(o):
                    tasks.append((convert_file, os.path.join(root, f), o))
    print(len(tasks), "to convert"); return run(a.jobs, tasks, "from-dir")


def from_archive(a):
    x = urllib.request.urlopen(f"https://archive.org/download/{a.item}/{a.item}_files.xml", timeout=60).read().decode()
    names = [n for n in re.findall(r'<file name="([^"]+)"', x) if re.search(a.pattern, n) and IMG.search(n)]
    tasks = [(convert_url, f"https://archive.org/download/{a.item}/{urllib.parse.quote(n)}", out_path(a.dst, n)) for n in names if not os.path.exists(out_path(a.dst, n))]
    print(len(names), "images in the item,", len(tasks), "to fetch and convert"); return run(a.jobs, tasks, a.item)


def pack(a):
    files = sorted(os.path.join(r, f) for r, _, fs in os.walk(a.src) for f in fs if not f.endswith(".part"))
    limit = int(a.part_gb * 1e9); parts = [[]]; size = 0
    for f in files:
        s = os.path.getsize(f)
        if size + s > limit and parts[-1]:
            parts.append([]); size = 0
        parts[-1].append(f); size += s
    os.makedirs(a.out, exist_ok=True); lines = []
    for i, part in enumerate(parts, 1):
        name = f"{a.name}-{i:02d}.zip"; p = os.path.join(a.out, name)
        with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
            for f in part:
                z.write(f, os.path.join(os.path.basename(a.src.rstrip('/')), os.path.relpath(f, a.src)))
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        lines.append(f"{h}  {name}  {len(part)} files"); print(" ", lines[-1], f"{os.path.getsize(p) / 1e9:.2f} GB")
    open(os.path.join(a.out, f"{a.name}-MANIFEST.txt"), "w").write("\n".join(lines) + "\n")
    print(f"done: {len(files)} files in {len(parts)} part(s); manifest {a.name}-MANIFEST.txt")


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("from-dir"); d.add_argument("--src", required=True); d.add_argument("--dst", required=True); d.add_argument("--jobs", type=int, default=8)
    r = sub.add_parser("from-archive"); r.add_argument("--item", required=True); r.add_argument("--pattern", default="^IMAGES/"); r.add_argument("--dst", required=True); r.add_argument("--jobs", type=int, default=8)
    p = sub.add_parser("pack"); p.add_argument("--src", required=True); p.add_argument("--name", required=True); p.add_argument("--out", default="packs"); p.add_argument("--part-gb", type=float, default=1.5)
    a = ap.parse_args()
    sys.exit(1 if {"from-dir": from_dir, "from-archive": from_archive, "pack": pack}[a.cmd](a) else 0)


if __name__ == "__main__":
    main()
