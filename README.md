# XAFS / HAXPES Reference Spectra Search Portal (prototype)

A static web page to find XAFS / HAXPES reference spectra by element and download only the ones you need.
It holds no spectral data itself: it searches public metadata (DOI records and a knowledge graph) and links directly to each source database.

**Live page:**
- English: https://matumot.github.io/xafs-portal-prototype/?lang=en
- 日本語: https://matumot.github.io/xafs-portal-prototype/?lang=ja

(The language can also be switched with the button at the top right of the page.)

> 日本語：XAFS・HAXPES の標準試料スペクトルを元素から検索し、必要なものだけをダウンロードできる Web ページ（試作版）です。画面右上で日本語／英語を切り替えられます。

## Features

| Tab | Sources | Filters | You get |
|---|---|---|---|
| **IXDB (XAFS, international)** | 7 databases via the International XAFS DB Portal: MDR (Japan), CLS (Canada), SSHADE/FAME and ESRF ID21 (France), XASLIB (USA), LISA (Italy), IHEP (China) | database, MDR facility, absorption edge | link to each database; DOI and zip for MDR; per-material links to COD, Materials Project XAS and AtomWork |
| **MDR (XAFS)** | NIMS MDR XAFS DB (SPring-8, KEK-PF, Hokkaido Univ., Ritsumeikan Univ., Aichi SR, Kyushu SR) | facility, edge, monochromator crystal, category | DOI and zip |
| **MDR (HAXPES)** | NIMS MDR HAXPES DB (SPring-8 BL46XU) | — | DOI and zip |

- Records of the same material are grouped across databases (IXDB tab), shown with Japanese/English names and formulas from [MatVoc Explorer](https://matvoc.nims.go.jp/explore/) (NIMS).
- IXDB tab: a **Related** column gives per-material links (as on the MatVoc pages linked from the IXDB portal): MatVoc, Materials Project XAS simulation, COD crystal structures, and AtomWork.
- Your selection is kept across tabs; download the MDR records as zip, save the list as CSV (DOI, URL), or copy citations.
- A **Related resources** box (same as the IXDB portal) links to Materials Project, MDR HAXPES DB, COD, CPDDB and AtomWork; if the selected element has HAXPES data, a button opens it in the MDR (HAXPES) tab.

## Usage

1. Choose a tab.
2. Click an element in the periodic table.
3. Tick the samples you want and use the **Download** section.

## How it works

```
Browser (docs/index.html: static page, no server needed)
 ├ MDR tabs  → DataCite REST API (DOI metadata), queried live
 └ IXDB tab  → docs/ixdb_index.js (index built from the IXDB knowledge graph), searched in the page
                 └ built by tools/build_ixdb_index.py (IXDB SPARQL + DataCite + MatVoc Explorer)
Spectral data → fetched directly from each database (MDR zip, database pages)
```

The NIMS MDR API, the IXDB SPARQL endpoint and MatVoc Explorer cannot be called from a browser (no CORS), so MDR is searched through DataCite and IXDB through a prebuilt index.

## Deploy and update

- **GitHub Pages:** source = `main` branch, `/docs` folder.
- **Run locally:** `python -m http.server 8000 --directory docs`, then open http://localhost:8000
- **Update the IXDB index:** `python tools/build_ixdb_index.py --out docs/ixdb_index.js` (Python 3.9+, no extra packages). The first run fetches about 1,200 MatVoc pages one at a time to respect its rate limit (~1 hour) and caches them in `cache/matvoc.json`; later runs reuse the cache. Use `--no-matvoc` to skip.

## Limitations

- MDR responds slowly: opening a DOI or starting a zip download can take 30 s to 1 min.
- Element highlighting in the MDR tabs reflects registrations as of 2026-10-22; other elements can still be searched.
- MatVoc names and links reflect the time the index was built; materials without a MatVoc entry (or without formula/links there) show the record title only.
- Prototype: information shown is based on the metadata registered in each database.

## License and data sources

- **Code** (`docs/index.html`, `tools/`): [MIT License](LICENSE)
- **IXDB index** (`docs/ixdb_index.js`): derived from M. Ishii et al., "International XAFS DB RDF and Ontology" (NIMS MDR, [doi:10.48505/nims.5513](https://doi.org/10.48505/nims.5513), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). Facility information for MDR records is taken from DataCite metadata (CC0). Material names, formulas and related links are taken from [MatVoc](https://matvoc.nims.go.jp/explore/) (NIMS Materials Data Platform); follow NIMS's terms of use.
- **Spectral data** are not included in this repository. Follow the terms of use and citation rules of each database:
  - MDR XAFS DB: [doi:10.48505/nims.1447](https://doi.org/10.48505/nims.1447) (data provided by JASRI: CC BY 4.0; for SPring-8 BL14B2 data also cite Ofuchi, Matsumoto, Honma, *Radiat. Phys. Chem.* **218** (2024) 111581)
  - MDR HAXPES DB: [doi:10.48505/nims.3056](https://doi.org/10.48505/nims.3056)
  - International XAFS DB Portal: M. Ishii et al., *J. Synchrotron Rad.* **32** (2025), [doi:10.1107/S1600577525002206](https://doi.org/10.1107/S1600577525002206)

## Author

Takahiro Matsumoto / JASRI (Japan Synchrotron Radiation Research Institute)
