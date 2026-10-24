#!/usr/bin/env python3

import csv, os, re, shutil, subprocess, sys
from collections import Counter

src, dest, abc = sys.argv[1], sys.argv[2], sys.argv[3]
TIMEOUT = 600   # seconds per file; slower files are listed in skipped.csv
EXCLUDE = {"live"}     # liveness benchmarks, not usable as safety properties


# (upper limit, size range text for the index)
BUCKETS = [(100, "< 100"), (1000, "100 - 1k"), (10000, "1k - 10k"),
           (100000, "10k - 100k"), (1000000, "100k - 1M"), (float("inf"), ">= 1M")]

PS = re.compile(r"i/o\s*=\s*(\d+)\s*/\s*(\d+).*?lat\s*=\s*(\d+).*?and\s*=\s*(\d+).*?lev\s*=\s*(\d+)")
YEAR = re.compile(r"(19|20)\d{2}")

def find_year(path):
    """closest folder above the file whose name is a 4-digit year"""
    for part in reversed(os.path.abspath(path).split(os.sep)[:-1]):
        if YEAR.fullmatch(part):
            return part
    return "unknown"

# ---- remove old buckets (only bucket_<n> folders, index.csv, skipped.csv) ----
if os.path.isdir(dest):
    for entry in os.listdir(dest):
        full = os.path.join(dest, entry)
        if re.fullmatch(r"bucket_\d+", entry) and os.path.isdir(full):
            shutil.rmtree(full)
    for stale in ("index.csv", "skipped.csv"):
        p = os.path.join(dest, stale)
        if os.path.exists(p):
            os.remove(p)
os.makedirs(dest, exist_ok=True)

src_abs, dest_abs = os.path.abspath(src), os.path.abspath(dest)

rows, skipped = [], []
found = Counter()
for root, dirs, files in os.walk(src):
    # never walk into the destination if it sits inside the source
    dirs[:] = sorted(d for d in dirs
    if d not in EXCLUDE and os.path.abspath(os.path.join(root, d)) != dest_abs)
    for fn in sorted(files):
        if not fn.lower().endswith((".aig", ".aag")):
            continue
        path = os.path.join(root, fn)
        rel = os.path.relpath(path, src)
        year = find_year(path)
        found[year] += 1
        try:
            r = subprocess.run([abc, "-c", f'read "{path}"; fold; ps'],
                               capture_output=True, text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            print("skipped (abc timeout):", path)
            skipped.append([year, rel, "timeout"])
            continue
        out = r.stdout + r.stderr
        m = PS.search(out)
        if not m:
            reason = (out.strip().splitlines() or ["no output"])[0][:150]
            print("skipped (abc failed):", path)
            skipped.append([year, rel, reason])
            continue
        i, o, lat, ands, lev = map(int, m.groups())
        size = i + lat + ands
        b, rng = next((n, t) for n, (lim, t) in enumerate(BUCKETS, 1) if size < lim)
        folder = os.path.join(dest, f"bucket_{b}")
        os.makedirs(folder, exist_ok=True)
        name = fn
        if os.path.exists(os.path.join(folder, name)):      # same name in another folder
            name = rel.replace(os.sep, "__")
        shutil.copy2(path, os.path.join(folder, name))
        rows.append([b, rng, year, name, rel, i, o, lat, ands, lev, size])

rows.sort(key=lambda x: (x[0], x[10], x[3]))
with open(os.path.join(dest, "index.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["bucket", "size_range", "year", "file", "orig_path", "i", "o", "lat", "and", "lev", "size_metric"])
    w.writerows(rows)

if skipped:
    with open(os.path.join(dest, "skipped.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "orig_path", "reason"])
        w.writerows(skipped)

done = Counter(r[2] for r in rows)
print("\nyear    found   bucketed")
for y in sorted(found):
    print(f"{y:<8}{found[y]:<8}{done[y]}")
print(f"\n{len(rows)} files done, {len(skipped)} skipped" + (" (see skipped.csv)" if skipped else ""))