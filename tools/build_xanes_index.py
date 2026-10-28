"""XANES 類似検索用の索引を作る：取り込み済みのスペクトル（docs/spectra/）を元素・吸収端ごとに
規格化し、吸収端付近の共通のエネルギー格子に載せて docs/spectra/xanes/<元素>_<吸収端>.json に書き出す。

規格化はページ（docs/index.html の normalizeXanes）と同じ手順にしている（変えるときは両方そろえること）。
  1. 吸収端の文献値 Ec（xraydb）の前後 [Ec-200, Ec+400] eV だけを使う（L 端が並ぶデータで別の端を拾わないため）
  2. E0 = 3 点平滑した一次微分の最大（Ec±30 eV の範囲で探す）
  3. 前縁を直線、吸収端より上を直線（範囲が 200 eV を超えるときは 2 次式）で近似し、edge step = 1 に規格化
  4. 吸収端より上は後縁の傾きを差し引いて平らにする（Athena の flatten と同じ考え方。試料の厚さや検出法による傾きの違いを減らす）
  5. 格子 Ec-30 〜 Ec+70 eV（0.5 eV 間隔）に線形補間（データのない所は null）

施設・ビームラインごとにエネルギーの校正基準が違う（Fe 箔の E0 が SPring-8 と海外 DB で約 5 eV 違うなど）ので、
DB・施設・分光結晶ごとに、その元素の金属（箔）の「半値エネルギー」（規格化 μ が 0.5 になるエネルギー）の中央値が、
全体の基準値 eh（各施設の中央値の中央値）になるようにずらしてから格子に載せる
（各スペクトルの sh：ずらした量、cal："fac"＝施設の代表値で補正、"ref"＝同時測定のリファレンスで 1 件ずつ補正、""＝補正なし）。
同時測定のリファレンスがあるものは、同じ施設でも測定ごとに E0 が動くことがあるので、そのリファレンスで 1 件ずつ合わせる。
施設・分光結晶ごとの代表的な補正量は src に入れ、ページでリファレンスのない測定データの初期値に使う。
金属は前縁に肩があり一次微分の最大の位置が安定しない（同じ Ni 箔でも 13 eV 違う例がある）ので、位置合わせには半値エネルギーを使う。
ページでは、利用者が読み込んだリファレンス（金属箔）の半値エネルギーを eh に合わせる。

使い方（build_spectra.py などで docs/spectra/ を更新した後に）:
    python build_xanes_index.py --spectra ../docs/spectra --index ../docs/ixdb_index.js
"""
import argparse
import collections
import json
import math
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import xraydb

GRID_LO, GRID_HI, GRID_STEP = -30.0, 70.0, 0.5
WIN_LO, WIN_HI, E0_RANGE = -200.0, 400.0, 30.0


def polyfit(x, y, order):
    """最小二乗（正規方程式）。x は平均からの差にする（ページの polyfit と同じ）"""
    m = sum(x) / len(x)
    k = order + 1
    A = [[0.0] * (k + 1) for _ in range(k)]
    for xv, yv in zip(x, y):
        p = [(xv - m) ** j for j in range(k)]
        for r in range(k):
            for c in range(k):
                A[r][c] += p[r] * p[c]
            A[r][k] += p[r] * yv
    for c in range(k):
        for r in range(c + 1, k):
            f = A[r][c] / A[c][c]
            for j in range(c, k + 1):
                A[r][j] -= f * A[c][j]
    b = [0.0] * k
    for r in range(k - 1, -1, -1):
        s = A[r][k] - sum(A[r][j] * b[j] for j in range(r + 1, k))
        b[r] = s / A[r][r]
    return m, b


def polyval(p, xv):
    m, b = p
    return sum(c * (xv - m) ** j for j, c in enumerate(b))


def normalize_xanes(x, y, ec):
    """吸収端 ec 付近を規格化・平坦化して (E0, 平坦化した規格化 μ のリスト（x に対応）) を返す。失敗時は None"""
    pts = [(a, b) for a, b in zip(x, y) if ec + WIN_LO <= a <= ec + WIN_HI and math.isfinite(b)]
    if len(pts) < 8:
        return None
    x = [p[0] for p in pts]
    y = [p[1] for p in pts]
    n = len(x)
    ys = [(y[max(0, i - 1)] + y[i] + y[min(n - 1, i + 1)]) / 3 for i in range(n)]
    i0, best = None, -math.inf
    for i in range(1, n - 1):
        if abs(x[i] - ec) > E0_RANGE or x[i + 1] == x[i - 1]:
            continue
        d = (ys[i + 1] - ys[i - 1]) / (x[i + 1] - x[i - 1])
        if d > best:
            best, i0 = d, i
    if i0 is None:
        return None
    e0 = x[i0]
    d_pre = min(30.0, 0.35 * (e0 - x[0]))
    d_post = min(50.0, 0.3 * (x[-1] - e0))
    pre_i = [i for i in range(n) if x[i] < e0 - d_pre] or list(range(3))
    post_i = [i for i in range(n) if x[i] > e0 + d_post] or list(range(n - 3, n))
    if len(pre_i) < 3:
        pre_i = list(range(3))
    if len(post_i) < 3:
        post_i = list(range(n - 3, n))
    order = 2 if x[post_i[-1]] - x[post_i[0]] > 200 else 1
    pre = polyfit([x[i] for i in pre_i], [y[i] for i in pre_i], 1)
    post = polyfit([x[i] for i in post_i], [y[i] for i in post_i], order)
    step = polyval(post, e0) - polyval(pre, e0)
    if not step > 0:
        return None
    out = []
    for xv, yv in zip(x, y):
        v = (yv - polyval(pre, xv)) / step
        if xv >= e0:  # 平坦化：後縁の曲線と前縁の直線の差の、E0 からの変化分を差し引く
            v -= (polyval(post, xv) - polyval(pre, xv) - step) / step
        out.append(v)
    # 半値エネルギー：E0 より前で最後に 0.5 を下回った点から、0.5 を上回る点までを線形補間
    eh = None
    for i in range(1, len(x)):
        if out[i - 1] < 0.5 <= out[i] and x[i] <= e0 + E0_RANGE:
            eh = x[i - 1] + (0.5 - out[i - 1]) / (out[i] - out[i - 1]) * (x[i] - x[i - 1])
            if x[i] >= e0:
                break
    return e0, x, out, eh


def on_grid(x, y, ec):
    grid = [ec + GRID_LO + GRID_STEP * i for i in range(int((GRID_HI - GRID_LO) / GRID_STEP) + 1)]
    out, j = [], 0
    for g in grid:
        while j < len(x) - 2 and x[j + 1] < g:
            j += 1
        if x[0] <= g <= x[-1] and x[j + 1] != x[j]:
            t = (g - x[j]) / (x[j + 1] - x[j])
            out.append(round(y[j] + t * (y[j + 1] - y[j]), 4))
        else:
            out.append(None)
    return out


def mdr_crystals():
    """MDR XAFS DB の DOI → 分光結晶（Si(111) など）。DataCite のキーワードから"""
    url = "https://api.datacite.org/dois?" + urllib.parse.urlencode({
        "query": 'subjects.subject:"collection - MDR XAFS DB"', "page[size]": "1000",
        "fields[dois]": "doi,subjects"}) + "&page[cursor]=1"
    out = {}
    while url:
        d = json.load(urllib.request.urlopen(url, timeout=120))
        for x in d["data"]:
            subj = [s["subject"] for s in x["attributes"].get("subjects", [])]
            out[x["attributes"]["doi"].lower()] = next((s for s in subj if re.fullmatch(r"[A-Za-z]+\(\d+\)", s)), "")
        url = d.get("links", {}).get("next")
    return out


def spectrum_file(spectra, r):
    """IXDB の記録 → docs/spectra/ のファイル（ページの plotKey と同じ規則）"""
    m = lambda pat, s: (re.search(pat, s or "") or [None, ""])[1]  # noqa: E731
    if r["db"] == "MDR":
        uuid = m(r"/datasets/([0-9a-f-]{36})$", r["url"])
        return spectra / f"{uuid}.json", f"MDR:{uuid}"
    ident = {"LISA": m(r"/data/([^/]+)\.xdi$", r["url"]), "XASLIB": m(r"/spectrum/(\d+)", r["url"]),
             "CLS": r.get("wid", "")}.get(r["db"], "")
    return (spectra / r["db"].lower() / f"{ident}.json", f"{r['db']}:{ident}") if ident else (None, "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spectra", default="../docs/spectra")
    ap.add_argument("--index", default="../docs/ixdb_index.js")
    args = ap.parse_args()
    spectra = Path(args.spectra)
    s = Path(args.index).read_text(encoding="utf-8")
    ix = json.loads(s[s.index("{"):s.rindex("}") + 1])
    mats = ix.get("materials", {})
    crystals = mdr_crystals()

    groups = collections.defaultdict(lambda: {"items": []})
    for r in ix["records"]:
        m = re.match(r"([A-Z][a-z]?) (K|L1|L2|L3)-edge$", r["edge"])
        path, key = spectrum_file(spectra, r)
        if not m or not path or not path.exists():
            continue
        el, edge = m.groups()
        try:
            ec = xraydb.xray_edge(el, edge).energy
        except Exception:  # noqa: BLE001
            continue
        series = json.loads(path.read_text(encoding="utf-8")).get("s", [])
        mv = mats.get(r.get("mat", ""), {})
        base = {"k": key, "n": mv.get("en") or r["group"], "ja": mv.get("ja", ""), "f": mv.get("f", ""),
                "db": r["db"], "fac": r.get("fac", ""), "bl": r.get("bl", ""),
                "c": crystals.get(r.get("doi", "").lower(), "") if r["db"] == "MDR" else ""}
        g = groups[(el, edge)]
        g["ec"] = ec
        main_s = next((x for x in series if x["t"] != "ref"), None)
        if main_s:
            nz = normalize_xanes(main_s["x"], main_s["y"], ec)
            if nz:
                # 同時測定のリファレンス（あいち SR の I2、北大の _ref、LISA・CLS・XASLIB の murefer など）があれば、その半値エネルギー
                ref_s = next((x for x in series if x["t"] == "ref"), None)
                rz = normalize_xanes(ref_s["x"], ref_s["y"], ec) if ref_s else None
                g["items"].append({**base, "e0": nz[0], "_x": nz[1], "_y": nz[2], "_eh": nz[3], "_rh": rz[3] if rz else None})

    out = spectra / "xanes"
    out.mkdir(exist_ok=True)
    summary = {}
    for (el, edge), g in sorted(groups.items()):
        if not g["items"]:
            continue
        # 施設ごとの校正のずれ：金属（MatVoc の組成式が元素そのもの、または名前に foil）の半値エネルギーの中央値を eh に合わせる
        src = lambda it: (it["db"], it["fac"], it["c"])  # noqa: E731
        med = lambda v: sorted(v)[len(v) // 2]  # noqa: E731
        foils = collections.defaultdict(list)
        for it in g["items"]:
            if (it["f"] == el or re.search(r"foil", it["n"], re.I)) and it["_eh"]:
                foils[src(it)].append(it["_eh"])
        src_eh = {k: med(v) for k, v in foils.items()}
        g["eh"] = round(med(list(src_eh.values())), 2) if src_eh else None
        for it in g["items"]:
            # 1) 同時測定のリファレンスがあり、その施設の金属（なければ基準値）から 15 eV 以内なら、そのリファレンスで 1 件ずつ合わせる
            #    （同じ施設でも測定ごとに E0 が動くことがあるため）
            # 2) なければ施設・分光結晶ごとの代表値（金属の半値エネルギーの中央値）で合わせる  3) どちらもなければ補正なし
            rh = it.pop("_rh")
            if rh and g["eh"] and abs(rh - src_eh.get(src(it), g["eh"])) < 15:
                sh, cal = g["eh"] - rh, "ref"
            elif src(it) in src_eh:
                sh, cal = g["eh"] - src_eh[src(it)], "fac"
            else:
                sh, cal = 0.0, ""
            it.pop("_eh")
            it.update({"sh": round(sh, 2), "cal": cal, "e0": round(it["e0"] + sh, 2),
                       "y": on_grid([v + sh for v in it.pop("_x")], it.pop("_y"), g["ec"])})
        # 施設・分光結晶ごとの代表的な補正量（ページで、リファレンスのない測定データの初期値に使う）
        g["src"] = {"|".join(k): round(g["eh"] - v, 2) for k, v in sorted(src_eh.items())}
        name = f"{el}_{edge}"
        payload = {"el": el, "edge": edge, "ec": g["ec"], "eh": g["eh"], "grid": [GRID_LO, GRID_HI, GRID_STEP],
                   "src": g.get("src", {}), "items": g["items"]}
        (out / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        summary[name] = len(g["items"])
    # generated：作成日（ページ下部に表示）、edges：元素_吸収端 → スペクトル数
    (out / "index.json").write_text(json.dumps({"generated": time.strftime("%Y-%m-%d"), "edges": summary},
                                               separators=(",", ":")), encoding="utf-8")
    print(f"{len(summary)} element-edges, {sum(summary.values())} spectra")


if __name__ == "__main__":
    main()
