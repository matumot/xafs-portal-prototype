"""International XAFS DB Portal (IXDB) の知識グラフ (SPARQL) から、
各国 XAFS データベースへのリンク索引を作り docs/ixdb_index.js に書き出す。

SPARQL エンドポイントはブラウザからの直接呼び出し (CORS) を許可していないため、
このスクリプトで事前に索引を作る。全件取得でも 1 秒程度。

使い方:
    python build_ixdb_index.py --out ../docs/ixdb_index.js
"""
import argparse
import collections
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

ENDPOINT = "https://materials-open-rdf.nims.go.jp/sparql"
GRAPH = "https://ixdb-rdf_10.nims.go.jp/"
QUERY = """
PREFIX s: <http://dice.nims.go.jp/ontology/mdr-xafs-ont/Schema#>
PREFIX obo: <http://purl.obolibrary.org/obo/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX prism: <http://prismstandard.org/namespaces/basic/2.0/>
SELECT ?w ?wl ?url ?doi ?edge ?sl ?mat FROM <%s> WHERE {
  ?e a s:AbsorptionEdge ; rdfs:label ?edge ; obo:OBI_0000299 ?w .
  ?w a s:Work .
  OPTIONAL { ?w rdfs:label ?wl }
  OPTIONAL { ?w rdfs:seeAlso ?url }
  OPTIONAL { ?w prism:doi ?doi }
  OPTIONAL { ?w obo:RO_0000057 ?smp . ?smp a s:Sample .
             OPTIONAL { ?smp rdfs:label ?sl } OPTIONAL { ?smp s:isNormalizedTo ?mat } }
}""" % GRAPH

# Work の名前空間 -> データベース
DBS = {
    "mdr-ont": "MDR",
    "cls-ont": "CLS",
    "fame-ont": "FAME",
    "xaslib-ont": "XASLIB",
    "esrf-ont": "ESRF",
    "lisa-ont": "LISA",
    "ihep-ont": "IHEP",
}


def clean_name(db, title, sample_label):
    t = re.sub(r"<[^>]+>", "", title or "").strip()
    if sample_label:
        return sample_label.strip()
    if db == "MDR":
        return re.sub(r"^XAFS spectrum of ", "", t)
    if db == "XASLIB":
        return re.sub(r"_rt_\d+$", "", re.sub(r"^Spectrum:\s*", "", t))
    if db == "LISA":
        return re.sub(r"(_\d{3})?\.xdi$", "", t)
    if db == "IHEP":
        return re.sub(r"_\d+$", "", t)
    return t


def mdr_facilities():
    """MDR XAFS DB の DOI -> (施設, ビームライン) を DataCite から取得（IXDB の RDF には施設情報がないため）"""
    out, page = {}, 1
    while True:
        q = urllib.parse.urlencode({"query": 'subjects.subject:"collection - MDR XAFS DB"', "page[size]": 1000,
                                    "page[number]": page, "fields[dois]": "doi,subjects,publisher"})
        req = urllib.request.Request("https://api.datacite.org/dois?" + q,
                                     headers={"Accept": "application/vnd.api+json", "User-Agent": "jasri-xafs-prototype/0.1"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)["data"]
        for item in data:
            a = item["attributes"]
            subj = [s["subject"] for s in a.get("subjects", [])]
            bl = next((s for s in subj if re.fullmatch(r"BL[-\w]*|AR-\w+", s)), "")
            out[a["doi"].lower()] = (a.get("publisher", ""), bl)
        if len(data) < 1000:
            return out
        page += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": QUERY})
    req = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json",
                                               "User-Agent": "jasri-xafs-prototype/0.1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        rows = json.load(r)["results"]["bindings"]
    g = lambda r, k: r.get(k, {}).get("value", "")  # noqa: E731

    recs, seen = [], set()
    for r in rows:
        w = g(r, "w")
        ns = w.split("#")[0].rstrip("/").split("/")[-1]
        db = DBS.get(ns, ns)
        edge = g(r, "edge")
        key = (w, edge)
        if key in seen:
            continue
        seen.add(key)
        m = re.match(r"([A-Z][a-z]?) (\S+)-edge", edge)
        recs.append({
            "db": db,
            "name": clean_name(db, g(r, "wl"), g(r, "sl")),
            "title": re.sub(r"<[^>]+>", "", g(r, "wl")),
            "url": g(r, "url"),
            "doi": g(r, "doi").replace("https://doi.org/", ""),
            "edge": edge,
            "el": m.group(1) if m else "",
            "mat": g(r, "mat").rsplit("/", 1)[-1],
        })

    # 同じ物質 (MatVoc ID) の代表名：MDR の名前を優先し、なければ最頻の名前
    by_mat = collections.defaultdict(list)
    for x in recs:
        if x["mat"]:
            by_mat[x["mat"]].append(x)
    for mat, xs in by_mat.items():
        mdr = [x["name"] for x in xs if x["db"] == "MDR"]
        rep = (collections.Counter(mdr) or collections.Counter(x["name"] for x in xs)).most_common(1)[0][0]
        for x in xs:
            x["group"] = rep
    for x in recs:
        x.setdefault("group", x["name"])

    fac = mdr_facilities()
    for x in recs:
        if x["db"] == "MDR":
            x["fac"], x["bl"] = fac.get(x["doi"].lower(), ("", ""))
    print("MDR facilities:", dict(collections.Counter(x.get("fac") or "?" for x in recs if x["db"] == "MDR")))

    payload = {"generated": time.strftime("%Y-%m-%d"), "graph": GRAPH, "records": recs}
    Path(args.out).write_text("window.IXDB_INDEX = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                              + ";\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(recs)} records, {len(by_mat)} materials, "
          + ", ".join(f"{k}={v}" for k, v in collections.Counter(x['db'] for x in recs).most_common()))


if __name__ == "__main__":
    main()
