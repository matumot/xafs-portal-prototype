"""スペクトルの表示で比べる文献値の表を作り、docs/spectra/refenergies.json に書き出す。

xafs: 吸収端のエネルギー（K・L1・L2・L3）。NIST X-ray Transition Energies Database (SRD 128,
      R. D. Deslattes et al., Rev. Mod. Phys. 75, 35 (2003), doi:10.18434/T4859Z) の表から。
      直接測定の値（Direct）を使い、組み合わせ値（Combined）と 3 eV 以上違うとき・ないときは Combined、
      どちらもなければ理論値（Theory）。どれを使ったかを src に記録する。
xps:  内殻の結合エネルギー。NIST X-ray Photoelectron Spectroscopy Database (SRD 20, doi:10.18434/T4T88K)
      の元素の推奨値（Recommended Elemental Reference Data。元素ごとの主なピーク 1 本）を優先し、
      それ以外の準位は Elam et al. の表（xraydb の吸収端エネルギー、Fermi 準位基準）で補う。

使い方:
    python build_reference_energies.py --out ../docs/spectra/refenergies.json
"""
import argparse
import html
import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import xraydb

UA = {"User-Agent": "jasri-xafs-prototype/0.1"}
NIST_EDGES = ("https://physics.nist.gov/cgi-bin/XrayTrans/search.pl?download=tab&element=All"
              "&trans=Kedge&trans=L1edge&trans=L2edge&trans=L3edge&lower=&upper=&units=eV")
NIST_XPS_REC = "https://srdata.nist.gov/xps/Recommend"
# 吸収端（X 線の準位名）→ 光電子の軌道名
ORBITAL = {"K": "1s", "L1": "2s", "L2": "2p1/2", "L3": "2p3/2", "M1": "3s", "M2": "3p1/2", "M3": "3p3/2",
           "M4": "3d3/2", "M5": "3d5/2", "N1": "4s", "N2": "4p1/2", "N3": "4p3/2", "N4": "4d3/2", "N5": "4d5/2",
           "N6": "4f5/2", "N7": "4f7/2", "O1": "5s", "O2": "5p1/2", "O3": "5p3/2", "O4": "5d3/2", "O5": "5d5/2"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.URLError as e:
        # Python の証明書ストアが古いと NIST のサーバー証明書を検証できないことがあるので、OS の証明書を使う curl で取り直す
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        return subprocess.run(["curl", "-sfL", "--max-time", "120", url], capture_output=True, check=True).stdout.decode("utf-8", "replace")


def nist_edges():
    out = {}
    for line in get(NIST_EDGES).splitlines():
        c = line.split("\t")
        if len(c) < 9 or not re.fullmatch(r"[A-Z][a-z]?", c[0]) or not c[2].endswith(" edge"):
            continue
        num = lambda s: float(s.replace(" ", "")) if s.strip() else None  # noqa: E731
        theory, direct, comb = num(c[3]), num(c[5]), num(c[7])
        if direct is not None and (comb is None or abs(direct - comb) < 3):
            v, src = direct, "direct"
        elif comb is not None:
            v, src = comb, "combined"
        else:
            v, src = theory, "theory"
        if v is not None:
            out.setdefault(c[0], {})[c[2].replace(" edge", "")] = {"v": v, "src": src}
    return out


def nist_xps_recommended():
    """推奨値の表（最初の表＝主な光電子ピーク）：元素 → {軌道: 結合エネルギー}"""
    s = get(NIST_XPS_REC)
    s = s[s.find("Total Records"):]  # 光電子ピークの表から（次の "Total Records" からはオージェの表）
    s = s[:s.find("Total Records", 20)]
    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", s, flags=re.S | re.I):
        cells = [re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]+>", "", c)))
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S | re.I)]
        if len(cells) >= 4 and re.fullmatch(r"[A-Z][a-z]?", cells[0]) and re.fullmatch(r"\d[spdf](\d/\d)?", cells[2]):
            try:
                out.setdefault(cells[0], {})[cells[2]] = float(cells[3])
            except ValueError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="../docs/spectra/refenergies.json")
    args = ap.parse_args()
    edges = nist_edges()
    rec = nist_xps_recommended()
    xps = {}
    for z in range(3, 93):
        el = xraydb.atomic_symbol(z)
        levels = {}
        for name, e in xraydb.xray_edges(el).items():
            if name in ORBITAL and e.energy > 0:
                levels[ORBITAL[name]] = {"v": round(e.energy, 2), "src": "elam"}
        for orb, v in rec.get(el, {}).items():
            keys = [orb] if "/" in orb else [k for k in levels if k.startswith(orb)] or [orb]  # "4d" は 4d3/2・4d5/2 の両方
            for k in keys:
                levels[k] = {"v": v, "src": "nist"}
        if levels:
            xps[el] = levels
    payload = {"xafs": edges, "xps": xps,
               "sources": {"xafs": "NIST SRD 128 (doi:10.18434/T4859Z)", "nist": "NIST SRD 20 recommended (doi:10.18434/T4T88K)",
                           "elam": "Elam, Ravel & Sieber, Radiat. Phys. Chem. 63, 121 (2002) via xraydb"}}
    Path(args.out).write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"edges: {len(edges)} elements, xps: {len(xps)} elements ({len(rec)} with NIST recommended values)")


if __name__ == "__main__":
    main()
