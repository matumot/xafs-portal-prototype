"""IXDB に含まれる海外 XAFS データベースのうち、LISA・XASLIB・CLS のスペクトルを取り出し、
docs/spectra/<db>/<ID>.json に書き出す（ページ上でクリックしたスペクトルのプロット用）。

これらのサイトはブラウザからの直接取得 (CORS) を許可していないため、このスクリプトで事前に取り出しておく。
IHEP は API が CORS を許可しているので、ページから直接取得する（ここでは扱わない）。
対象は docs/ixdb_index.js の記録（build_ixdb_index.py で作成）。

  LISA  : 記録の URL が XDI ファイル（列 mutrans / mufluor / murefer）。ID はファイル名（.xdi を除く）
  XASLIB: スペクトルのページから生データ（XDI, /rawfile/...）を辿る。ID はスペクトル番号
          列 i0・itrans・ifluor・irefer からは μt = ln(I0/It)、If/I0、リファレンス ln(It/Iref) を計算
  CLS   : POST /xasgetcompounds（化合物名・"<元素>_id<ID>"・元素）が XDI の内容と μ を返す。ID は IXDB 上のスペクトル ID

出力形式は build_spectra.py と同じ（{"src": DB, "s": [{"n", "t", "x", "y"}], "lic": ライセンス（分かる場合）}）。
既に出力があるものは飛ばすので、途中で止めても続きから再実行できる。

使い方:
    python build_overseas_spectra.py --index ../docs/ixdb_index.js --out ../docs/spectra
"""
import argparse
import concurrent.futures as cf
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from build_spectra import compact, log_ratio, write_manifest

UA = {"User-Agent": "jasri-xafs-prototype/0.1"}


def get(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1 or getattr(e, "code", 0) == 404:  # 404 は再試行しても変わらない
                raise
            time.sleep(5 * (i + 1))


def parse_xdi(s):
    """XDI → ({列名: 値の列}, ヘッダー)。列名は "# Column.N: name unit" から取る。"""
    names, head, rows = {}, {}, []
    for line in s.splitlines():
        if line.startswith("#"):
            m = re.match(r"#\s*Column\.(\d+):\s*(\S+)", line)
            if m:
                names[int(m.group(1)) - 1] = m.group(2).lower()
            m = re.match(r"#\s*([\w.]+):\s*(.*)", line)
            if m:
                head[m.group(1)] = m.group(2).strip()
            continue
        try:
            v = [float(x) for x in line.split()]
        except ValueError:
            continue
        if v:
            rows.append(v)
    cols = {name: [r[i] for r in rows if len(r) > i] for i, name in names.items()}
    return cols, head


def xdi_series(name, s):
    cols, head = parse_xdi(s)
    E = cols.get("energy")
    if not E:
        return [], head
    out = []
    for c, kind in (("mutrans", "mu"), ("mufluor", "fl"), ("mutey", "ey")):
        if c in cols:
            out.append((name, kind, E, cols[c]))
    # 列名が "I0_eh2"・"I1_eh2" のような生データ（LISA の一部）は、値の入っている最初の I0・I1 を使う
    pick = lambda pat: next((v for k, v in cols.items() if re.match(pat, k) and any(v)), None)  # noqa: E731
    i0 = cols.get("i0") or pick(r"i0_")
    if "itrans" not in cols and i0 and pick(r"i1_"):
        cols["itrans"] = pick(r"i1_")
    if not out and i0:
        if "itrans" in cols:
            out.append((name, "mu", E, log_ratio(i0, cols["itrans"])))
        if "ifluor" in cols:
            out.append((name + " (fluor)" if out else name, "fl", E,
                        [f / z if z > 0 else math.nan for f, z in zip(cols["ifluor"], i0)]))
    if "murefer" in cols:
        out.append((name + " (ref)", "ref", E, cols["murefer"]))
    elif "irefer" in cols and "itrans" in cols:
        out.append((name + " (ref)", "ref", E, log_ratio(cols["itrans"], cols["irefer"])))
    return out, head


def lisa(rec):
    url = rec["url"]
    name = url.rsplit("/", 1)[-1]
    series, head = xdi_series(name, get(url))
    return name[:-4], series, ""


def xaslib(rec):
    sid = re.search(r"/spectrum/(\d+)", rec["url"]).group(1)
    page = get(rec["url"])
    raw = re.search(r'href="(/rawfile/[^"]+)"', page).group(1)
    name = raw.rsplit("/", 1)[-1]
    series, head = xdi_series(name, get("https://xaslib.xrayabsorption.org" + urllib.parse.quote(raw)))
    return sid, series, ""


def cls(rec):
    # サイトでスペクトルをクリックしたときと同じ呼び出し（化合物名・"<元素>_id<ID>"・元素）。
    # 検索 API (/search) は化合物の 1 件目を返すので使わない
    wid, el = rec["wid"], rec["el"]
    sid = f"{el}_id{wid}"
    name = re.sub(rf"_{re.escape(wid)}$", "", rec["title"])
    fetch = lambda n: json.loads(get("https://xasdb.lightsource.ca/xasgetcompounds",  # noqa: E731
                                     json.dumps({"name": n, "id": sid, "element": el}).encode())).get("spectrum") or {}
    try:
        sp = fetch(name)
    except urllib.error.HTTPError as e:
        # CLS 側で化合物名の表記が変わったもの（"Vanadium foil" → "Vanadium Foil" など）は 404 になるので、
        # ID で検索して今の化合物名を引き直す
        if e.code != 404:
            raise
        d = json.loads(get("https://xasdb.lightsource.ca/search", json.dumps({"search": wid}).encode()))
        cmds = d.get("cmds", []) if isinstance(d, dict) else []
        cur = next((c["compound"] for c in cmds if sid in c.get("sids", [])), None)
        if not cur:
            raise ValueError(f"CLS has no spectrum {sid}") from None
        sp = fetch(cur)
    if not (sp.get("title") or "").endswith("_id" + wid):
        raise ValueError(f"CLS returned {sp.get('title')} for {wid}")
    h = sp.get("header", {})
    mode = (h.get("Beamline.scan_mode") or "").lower()
    kind = "fl" if "fluor" in mode else "ey" if "electron" in mode or "tey" in mode else "mu"
    name = (sp.get("filepath") or sp.get("title") or wid).rsplit("/", 1)[-1]
    out = [(name, kind, sp.get("energy") or [], sp.get("Mu") or [])]
    if sp.get("murefer"):
        out.append((name + " (ref)", "ref", sp["energy"], sp["murefer"]))
    return wid, out, (h.get("Scan.license") or "").strip()


HANDLERS = {"LISA": lisa, "XASLIB": xaslib, "CLS": cls}


def ident(rec):
    """出力ファイル名にする ID（ページ側の plotKey と同じ規則）"""
    if rec["db"] == "LISA":
        return rec["url"].rsplit("/", 1)[-1][:-4]
    if rec["db"] == "XASLIB":
        return re.search(r"/spectrum/(\d+)", rec["url"]).group(1)
    return rec["wid"]


def build_one(rec, out_dir):
    path = out_dir / rec["db"].lower() / f"{ident(rec)}.json"
    if path.exists():
        return rec, "skip"
    _, series, lic = HANDLERS[rec["db"]](rec)
    series = [compact(*s) for s in series if len(s[2]) > 5]
    payload = {"src": rec["db"], "s": series}
    if lic:
        payload["lic"] = lic
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")  # 中断しても書きかけのファイルを残さない
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)
    return rec, f"{len(series)} series"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="../docs/ixdb_index.js")
    ap.add_argument("--out", default="../docs/spectra")
    ap.add_argument("--db", nargs="*", default=list(HANDLERS), help="対象のデータベース")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    s = Path(args.index).read_text(encoding="utf-8")
    recs = json.loads(s[s.index("{"):s.rindex("}") + 1])["records"]
    recs = list({(r["db"], ident(r)): r for r in recs if r["db"] in args.db}.values())  # 吸収端違いの重複を除く
    print(f"{len(recs)} spectra")
    fails = 0
    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(build_one, r, Path(args.out)): r for r in recs}
        for i, f in enumerate(cf.as_completed(futs), 1):
            rec = futs[f]
            try:
                _, msg = f.result()
                if msg != "skip":
                    print(f"[{i}/{len(recs)}] {rec['db']} {ident(rec)}: {msg}", flush=True)
            except Exception as e:
                fails += 1
                print(f"[{i}/{len(recs)}] FAILED {rec['db']} {ident(rec)}: {e}", flush=True)
    print(f"done, {fails} failed (re-run to retry)")
    write_manifest(args.out)


if __name__ == "__main__":
    main()
