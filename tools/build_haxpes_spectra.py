"""MDR HAXPES DB の各データセットから HAXPES スペクトルを取り出し、
docs/spectra/haxpes/<MDR の ID>.json に書き出す（ページ上でクリックしたデータセットのプロット用）。

MDR はブラウザからの直接取得 (CORS) を許可していないため、build_spectra.py と同じく事前に取り出す。
各データセットの *_sp.csv（施設の加工データ）を使う。形式は
    #x,Binding Energy,eV,reverse
    #y,Intensity,a.u.
    #legend,wide,VB,Al_1s,...
の後に、領域ごとの「結合エネルギー, 強度」が列の組で並ぶ（領域ごとに点数が違うので空欄あり）。
raw_data.zip（装置の生データ）は使わない。

出力は {"src": "HAXPES", "axis": "be", "lic": ライセンス, "s": [{"n": 領域, "t": "xps", "x", "y"}]}。
既に出力があるデータセットは飛ばす。MDR に負荷をかけないよう 1 件ずつ取得する。

使い方:
    python build_haxpes_spectra.py --out ../docs/spectra
"""
import argparse
import json
import math
from pathlib import Path

import yaml

from build_spectra import compact, fetch_zip, list_datasets, text, write_manifest

COLLECTION = "collection - MDR HAXPES DB"


def parse_sp_csv(s):
    legend, cols = [], []
    for line in s.splitlines():
        if line.startswith("#legend,"):
            legend = [x.strip() for x in line.split(",")[1:]]
            cols = [([], []) for _ in legend]
            continue
        if line.startswith("#") or not line.strip() or not legend:
            continue
        cells = line.split(",")
        for i, (xs, ys) in enumerate(cols):
            try:
                x, y = float(cells[2 * i]), float(cells[2 * i + 1])
            except (ValueError, IndexError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                xs.append(x)
                ys.append(y)
    return [(name.replace("_", " "), "xps", xs, ys) for name, (xs, ys) in zip(legend, cols)]


def build_one(rec, out_dir):
    path = out_dir / f"{rec['uuid']}.json"
    if path.exists():
        return "skip"
    z = fetch_zip(rec["uuid"])
    names = z.namelist()
    # 通常は *_sp.csv だが名前の違うものもあるので、"#legend" 行のある CSV を使う（metadata.schema.csv を拾わない）
    csv = next((text(z, n) for n in sorted(names, key=lambda n: not n.lower().endswith("_sp.csv"))
                if n.lower().endswith(".csv") and "#legend," in text(z, n)), "")
    series = [compact(*s) for s in parse_sp_csv(csv) if len(s[2]) > 5]
    lic = ""
    meta = next((n for n in names if n.endswith("metadata.all.yml")), None)
    if meta:
        lic = ((yaml.safe_load(text(z, meta)) or {}).get("data_info", {}).get("license") or {}).get("name", "")
    payload = {"src": "HAXPES", "axis": "be", "s": series}
    if lic:
        payload["lic"] = lic
    tmp = path.with_suffix(".tmp")  # 中断しても書きかけのファイルを残さない
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return f"{len(series)} regions"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../docs/spectra")
    args = ap.parse_args()
    out_dir = Path(args.out) / "haxpes"
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = list_datasets(COLLECTION)
    print(f"{len(recs)} datasets")
    fails = 0
    for i, rec in enumerate(recs, 1):
        try:
            msg = build_one(rec, out_dir)
            if msg != "skip":
                print(f"[{i}/{len(recs)}] {rec['uuid']}: {msg}", flush=True)
        except Exception as e:
            fails += 1
            print(f"[{i}/{len(recs)}] FAILED {rec['uuid']}: {e}", flush=True)
    print(f"done, {fails} failed (re-run to retry)")
    write_manifest(args.out, {"HAXPES": len(recs)})


if __name__ == "__main__":
    main()
