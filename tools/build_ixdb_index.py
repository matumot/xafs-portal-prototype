"""International XAFS DB Portal (IXDB) の知識グラフ (SPARQL) から、
各国 XAFS データベースへのリンク索引を作り docs/ixdb_index.js に書き出す。

SPARQL エンドポイントはブラウザからの直接呼び出し (CORS) を許可していないため、
このスクリプトで事前に索引を作る。SPARQL は全件取得でも 1 秒程度。
あわせて MDR の施設情報 (DataCite) と、物質ごとの名称（日本語・英語）・組成式・関連リンク
（Materials Project の XAS、COD、AtomWork; MatVoc Explorer）を取り込む。
MatVoc は初回のみ約 1,200 ページを取得（アクセス制限を避けて 1 件ずつ、1 時間程度）し、cache/matvoc.json に保存して再利用する。

使い方:
    python build_ixdb_index.py --out ../docs/ixdb_index.js
"""
import argparse
import collections
import json
import re
import time
import urllib.parse
import urllib.error
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


MATVOC_PAGE = "https://matvoc.nims.go.jp/explore/en/results/{}"


def parse_matvoc(html):
    """MatVoc Explorer の物質ページから名称・組成式・関連リンクを取り出す。
    「Semantic Relatives」以降は関連する別の物質の情報なので、名称・データ欄はその手前だけを読む。"""
    main_part = html.split("Semantic Relatives", 1)[0]
    text = lambda s: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()  # noqa: E731
    label = lambda lang: next((text(m) for m in re.findall(  # noqa: E731
        rf'<th class="text-center text-nowrap">{lang}</th>\s*<td>(.*?)</td>', main_part, re.S)), "")
    formula = re.search(r"<dt>chemical formula</dt>(.*?)</dl>", main_part, re.S)
    mp = re.search(r'href="(https://next-gen\.materialsproject\.org/xas\?formula=[^"]+)"', main_part)
    aw = re.search(r'href="(https://crystdb\.nims\.go\.jp/crystdb/search-materials-list\?[^"]+)"', html)
    cod = list(dict.fromkeys(re.findall(r"crystallography\.net/cod/(\d+)\.html", main_part)))
    info = {"en": label("English"), "ja": label("Japanese"), "f": text(formula.group(1)) if formula else "",
            "mp": mp.group(1) if mp else "", "aw": aw.group(1).replace("&amp;", "&") if aw else "", "cod": cod}
    return {k: v for k, v in info.items() if v}


def matvoc_info(qids, cache_file, interval=1.0):
    """各物質 (MatVoc ID) の情報を MatVoc Explorer から取得。結果は cache_file に保存し、2 回目以降は再利用する。
    MatVoc Explorer もブラウザからの直接呼び出し (CORS) 不可のため、索引作成時に取り込む。
    並列で取得すると 429 (Too Many Requests) になるため、1 件ずつ間隔をあけ、429 のときは待ってから再試行する。"""
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    todo = [q for q in qids if q not in cache]

    def fetch(q):
        wait = 30
        for _ in range(6):
            try:
                req = urllib.request.Request(MATVOC_PAGE.format(q), headers={"User-Agent": "jasri-xafs-prototype/0.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return parse_matvoc(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    return None
                time.sleep(int(e.headers.get("Retry-After") or wait))
                wait = min(wait * 2, 300)
            except Exception:  # noqa: BLE001
                time.sleep(5)
        return None

    for n, q in enumerate(todo, 1):
        info = fetch(q)
        if info is not None:
            cache[q] = info
        if n % 50 == 0 or n == len(todo):
            print(f"  MatVoc {n}/{len(todo)}", flush=True)
            cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        time.sleep(interval)
    print(f"MatVoc: {sum(1 for q in qids if q in cache)}/{len(qids)} materials ({len(todo)} fetched)")
    return {q: cache[q] for q in qids if q in cache}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default=str(Path(__file__).resolve().parent.parent / "cache" / "matvoc.json"),
                    help="MatVoc の取得結果を保存するファイル（再実行時に再利用）")
    ap.add_argument("--no-matvoc", action="store_true", help="MatVoc から名称・関連リンクを取り込まない")
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

    materials = {} if args.no_matvoc else matvoc_info(sorted(by_mat), Path(args.cache))

    payload = {"generated": time.strftime("%Y-%m-%d"), "graph": GRAPH, "records": recs, "materials": materials}
    Path(args.out).write_text("window.IXDB_INDEX = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                              + ";\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(recs)} records, {len(by_mat)} materials, "
          + ", ".join(f"{k}={v}" for k, v in collections.Counter(x['db'] for x in recs).most_common()))


if __name__ == "__main__":
    main()
