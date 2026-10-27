"""MDR XAFS DB の各データセット（work）から XAFS スペクトルを取り出し、
docs/spectra/<MDR の ID>.json に書き出す（ページ上でクリックしたデータセットのプロット用）。

MDR（API・zip・ファイル本体）はブラウザからの直接取得 (CORS) を許可していないため、
このスクリプトで事前に取り出しておく。データセット一覧は DataCite から取得する。

ファイル形式は MDR XAFS DB Readme (https://mdr.nims.go.jp/datasets/73c9765a-2934-4fad-8166-f85c6486991e)
の施設ごとの説明 (03_data_format_*) に従う。
  SPring-8 : *.txt（Athena 形式。*.dat から E と μt = ln(I0/I1) を計算した加工データ）
  北大触媒研: *.txt（Athena 形式の加工データ。_ref はリファレンス）
  KEK      : *.dat（PF9809 形式の生データ）→ μt = ln(I0/I) を計算
  あいち SR : *.dat（PF9809 形式。I0, I1, I2）→ 試料 ln(I0/I1)、リファレンス ln(I1/I2)
  立命館    : *.tey / *.pfy など（施設で規格化済み）と、*.dat から metadata.yml の式で計算した生の比 (I/I0)
  SAGA-LS  : *.tey など（施設の加工データ I/I0）

出力は {"src": 施設, "s": [{"n": ファイル名, "t": 種類, "x": [eV...], "y": [...]}]}。
種類 t: "mu"（μt）、"fl"（蛍光 If/I0）、"ey"（電子収量など I/I0）、"norm"（施設で規格化済み）、"ref"（リファレンス）
点数が多いもの（Quick XAFS など）は 1,000 点程度に平均して間引く。

既に出力があるデータセットは飛ばすので、途中で止めても続きから再実行できる。

使い方:
    python build_spectra.py --out ../docs/spectra
"""
import argparse
import concurrent.futures as cf
import io
import json
import math
import re
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import yaml

DATACITE = "https://api.datacite.org/dois"
COLLECTION = "collection - MDR XAFS DB"
MAX_POINTS = 1000
HC = 12398.42  # eV·Å


def list_datasets():
    url = DATACITE + "?" + urllib.parse.urlencode({
        "query": f'subjects.subject:"{COLLECTION}"', "page[size]": "1000",
        "fields[dois]": "doi,titles,url,publisher"}) + "&page[cursor]=1"
    out = []
    while url:
        d = json.load(urllib.request.urlopen(url, timeout=120))
        for x in d["data"]:
            a = x["attributes"]
            uuid = (a.get("url") or "").rstrip("/").split("/")[-1]
            if uuid:
                out.append({"uuid": uuid, "doi": a["doi"], "pub": a["publisher"]})
        url = d.get("links", {}).get("next")
    return out


def fetch_zip(uuid, tries=5):
    for i in range(tries):
        try:
            with urllib.request.urlopen(f"https://mdr.nims.go.jp/datasets/{uuid}.zip", timeout=300) as r:
                return zipfile.ZipFile(io.BytesIO(r.read()))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(10 * (i + 1))


def text(z, name):
    b = z.read(name)
    for enc in ("utf-8", "cp932", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass


def numeric_rows(s, ncol=2, sep=None):
    rows = []
    for line in s.splitlines():
        p = line.replace(",", " ").split() if sep is None else line.split(sep)
        try:
            v = [float(x) for x in p[:ncol]]
        except ValueError:
            continue
        if len(v) == ncol and all(math.isfinite(x) for x in v):
            rows.append(v)
    return rows


def two_col(s):
    rows = numeric_rows(s, 2)
    return [r[0] for r in rows], [r[1] for r in rows]


def parse_pf9809(s):
    """PF9809 形式 → (E, {チャンネル番号: 計数}, モード, 検出法)。計数はオフセット（毎秒）×時間を差し引く。"""
    lines = s.splitlines()
    d = float(re.search(r"D=\s*([\d.]+)", s).group(1))
    det = lines[5][10:40].strip() if len(lines) > 5 else ""
    i_mode = next(i for i, l in enumerate(lines) if l.strip().startswith("Mode"))
    # Mode／Offset 行は先頭の Angle(c) 列に見出しが入るので、値は Angle(o) 列から始まる
    modes = [0] + [int(float(x)) for x in lines[i_mode].split()[1:]]
    offs = [0.0] + [float(x) for x in lines[i_mode + 1].split()[1:]]
    E, ch = [], {k: [] for k in range(3, len(modes))}
    for line in lines[i_mode + 2:]:
        p = line.split()
        if len(p) < len(modes):
            continue
        try:
            v = [float(x) for x in p[:len(modes)]]
        except ValueError:
            continue
        ang = math.radians(v[1] or v[0])
        E.append(HC / (2 * d * math.sin(ang)))
        for k in ch:
            ch[k].append(v[k] - offs[k] * v[2])
    return E, ch, modes, det


def pf9809_series(name, s):
    E, ch, modes, det = parse_pf9809(s)
    i0 = [k for k in ch if modes[k] == 1]
    tr = [k for k in ch if modes[k] == 2]
    fl = [k for k in ch if modes[k] >= 3]
    if not i0:
        return []
    I0 = ch[i0[0]]
    out = []
    if "fluo" in det.lower() and fl:
        y = [sum(ch[k][i] for k in fl) / I0[i] if I0[i] > 0 else math.nan for i in range(len(E))]
        out.append((name, "fl", E, y))
    elif tr:
        out.append((name, "mu", E, log_ratio(I0, ch[tr[0]])))
        if len(tr) > 1:  # あいち SR などの I2：I1 と I2 の間のリファレンス箔
            out.append((name + " (ref)", "ref", E, log_ratio(ch[tr[0]], ch[tr[1]])))
    return out


def log_ratio(a, b):
    return [math.log(x / y) if x > 0 and y > 0 else math.nan for x, y in zip(a, b)]


def rit_series(z, names):
    """立命館：加工データ（規格化済み）と、metadata.yml の式で .dat から計算した生の比。"""
    out = []
    meta = yaml.safe_load(text(z, "metadata.yml")) if "metadata.yml" in names else {}
    fmts = {}
    for f in (find_key(meta, "processed_data_format") or []):
        cols = f.get("columns") or []
        if len(cols) > 1:
            fmts[f.get("extension")] = (cols[1].get("formula") or "", cols[1].get("name") or "")
    dat = next((n for n in names if n.lower().endswith(".dat")), None)
    rows = None
    if dat:
        lines = text(z, dat).splitlines()
        i_head = next((i for i, l in enumerate(lines) if "Io" in l and "," in l), None)
        if i_head is not None:
            rows = [r for r in (numeric_row(l) for l in lines[i_head + 1:]) if r]
    for n in sorted(names):
        ext = n.rsplit(".", 1)[-1].lower()
        if ext not in ("tey", "pey", "pfy", "ipfy", "tfy"):
            continue
        x, y = two_col(text(z, n))
        if x:
            out.append((n, "norm", x, y))
        formula = fmts.get(ext, ("", ""))[0]
        m = re.fullmatch(r"\s*column\[(\d+)\]\s*/\s*column\[(\d+)\]\s*", formula)
        if rows and m:
            a, b = int(m.group(1)), int(m.group(2))
            pts = [(r[2], r[a] / r[b]) for r in rows if len(r) > max(a, b) and r[b] > 0]
            if pts:
                out.append((n.rsplit(".", 1)[0] + f".dat {ext.upper()}", "ey", [p[0] for p in pts], [p[1] for p in pts]))
    return out


def numeric_row(line):
    try:
        return [float(x) for x in line.split(",")]
    except ValueError:
        return None


def find_key(d, key):
    if isinstance(d, dict):
        for k, v in d.items():
            if k == key:
                return v
            r = find_key(v, key)
            if r is not None:
                return r
    elif isinstance(d, list):
        for v in d:
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def extract(z, pub):
    names = [n for n in z.namelist() if not n.endswith("/")]
    base = lambda n: n.rsplit("/", 1)[-1]
    out = []
    if pub in ("SPring-8", "Hokkaido University"):
        for n in sorted(names, key=base):
            if n.lower().endswith(".txt"):
                b = base(n)[:-4]
                kind = "ref" if b.endswith("_ref") else "mu"
                x, y = two_col(text(z, n))
                out.append((base(n), kind, x, y))
    elif pub in ("KEK", "Aichi Synchrotron Radiation Center"):
        for n in sorted(names, key=base):
            if n.lower().endswith(".dat"):
                out += pf9809_series(base(n), text(z, n))
    elif pub == "Ritsumeikan University":
        out = rit_series(z, names)
    if not out:  # SAGA-LS など：2 列の加工データ（I/I0）
        for n in sorted(names, key=base):
            if n.rsplit(".", 1)[-1].lower() in ("tey", "pey", "pfy", "tfy", "fy", "xmu", "txt", "nor"):
                x, y = two_col(text(z, n))
                out.append((base(n), "ey", x, y))
        if not out:
            for n in sorted(names, key=base):
                if n.lower().endswith(".dat"):
                    try:
                        out += pf9809_series(base(n), text(z, n))
                    except Exception:
                        pass
    return [compact(*s) for s in out if len(s[2]) > 5]


def compact(name, kind, x, y):
    pts = sorted((a, b) for a, b in zip(x, y) if math.isfinite(a) and math.isfinite(b))
    if len(pts) > MAX_POINTS:  # 平均して間引く
        k = math.ceil(len(pts) / MAX_POINTS)
        pts = [(sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g))
               for g in (pts[i:i + k] for i in range(0, len(pts), k))]
    return {"n": name, "t": kind, "x": [round(p[0], 2) for p in pts], "y": [float(f"{p[1]:.5g}") for p in pts]}


def build_one(rec, out_dir):
    path = out_dir / f"{rec['uuid']}.json"
    if path.exists():
        return rec, "skip"
    z = fetch_zip(rec["uuid"])
    series = extract(z, rec["pub"])
    tmp = path.with_suffix(".tmp")  # 中断しても書きかけのファイルを残さない
    tmp.write_text(json.dumps({"src": rec["pub"], "s": series}, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return rec, f"{len(series)} series"


def write_manifest(root):
    """取り込み済み（スペクトルが 1 本以上ある）ものの ID 一覧を root/available.json に書く。
    ページはこれを見て、未取り込みのものを「プロット（準備中）」と表示する。
    build_spectra.py と build_overseas_spectra.py の最後に毎回作り直す。"""
    root = Path(root)
    out = {}
    for db, d in [("MDR", root)] + [(x.name.upper(), x) for x in sorted(root.iterdir()) if x.is_dir()]:
        ids = []
        for f in sorted(d.glob("*.json")):
            if f.name == "available.json":
                continue
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("s"):
                    ids.append(f.stem)
            except ValueError:
                pass
        out[db] = ids
    (root / "available.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print("available:", {k: len(v) for k, v in out.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../docs/spectra")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="試験用：先頭 N 件だけ")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = list_datasets()
    if args.limit:
        recs = recs[:args.limit]
    print(f"{len(recs)} datasets")
    fails = []
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(build_one, r, out_dir) for r in recs]
        for i, f in enumerate(cf.as_completed(futs), 1):
            try:
                rec, msg = f.result()
                if msg != "skip":
                    print(f"[{i}/{len(recs)}] {rec['pub']} {rec['uuid']}: {msg}", flush=True)
            except Exception as e:
                fails.append(str(e))
                print(f"[{i}/{len(recs)}] FAILED: {e}", flush=True)
    print(f"done, {len(fails)} failed (re-run to retry)")
    write_manifest(out_dir)


if __name__ == "__main__":
    main()
