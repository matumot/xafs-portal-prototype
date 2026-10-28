# XAFS / HAXPES Reference Spectra Search Portal (prototype)

A static web page to find XAFS / HAXPES reference spectra by element and download only the ones you need.
It searches public metadata (DOI records and a knowledge graph) and links directly to each source database; for MDR XAFS DB it also plots each dataset's spectrum on the page.

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
- MDR XAFS records (MDR tab, and MDR rows in the IXDB tab) and IXDB records from IHEP, LISA, XASLIB and CLS have a **Plot** button that shows the dataset's spectrum on the page: raw (μt = ln(I0/I), If/I0 or I/I0 as provided by each facility) or background-subtracted and normalized (simple pre-edge line / post-edge fit, edge step = 1), full range or XANES region. Datasets with several files (repeated scans, reference foil, TEY/PFY) can be switched.
- MDR HAXPES records also have a **Plot** button: intensity vs. binding energy (high to low), with the regions of each dataset (wide, VB, core levels) selectable.
- **XANES matching** tab: load your XAFS data (2-column text, Athena, XDI or PF9809 .dat) and a reference (e.g. metal foil) measured under the same conditions, choose the element and edge (and optionally the database/facility and mono crystal), and get the most similar database spectra in the XANES region, with an overlay plot. The energy is aligned with the reference (or, without one, with the typical shift of the chosen facility) and can be fine-tuned with a slider while the ranking updates; database spectra are aligned individually with their own simultaneously measured reference where available, otherwise per facility using the half-step energy of the metal (foil). The compared range is selectable, and the overlap of measured ranges is shown. Six similarity metrics (Pearson, derivative Pearson, cosine, Spearman, R-factor, Ruzicka) and their mean rank are shown, with references to the papers in the page. Your files are processed only in the browser.
- Plots show reference values as green dashed lines: XAFS edge energies from the NIST X-ray Transition Energies Database (SRD 128; direct measurement preferred), with the difference from the data's E0; HAXPES core-level binding energies from the NIST XPS Database (SRD 20) recommended values, completed with Elam et al. (xraydb) for levels without one.
- The page footer shows how many spectra have been imported for plotting per database and when; records not imported yet show "Plot (in preparation)".
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
Plots       → docs/spectra/<MDR ID>.json, built by tools/build_spectra.py from each MDR XAFS DB zip
              docs/spectra/haxpes/<MDR ID>.json, built by tools/build_haxpes_spectra.py (*_sp.csv of each dataset)
              docs/spectra/{lisa,xaslib,cls}/<ID>.json, built by tools/build_overseas_spectra.py
              docs/spectra/xanes/<El>_<edge>.json: normalized XANES on a common grid for matching, built by tools/build_xanes_index.py
              docs/spectra/available.json: imported IDs, totals and import dates (written by each build script)
              IHEP: fetched live from its API (CORS allowed)
```

The NIMS MDR API, the IXDB SPARQL endpoint and MatVoc Explorer cannot be called from a browser (no CORS), so MDR is searched through DataCite and IXDB through a prebuilt index. For the same reason the spectra for plotting are extracted in advance.

`tools/build_spectra.py` follows the file formats in the [MDR XAFS DB Readme](https://mdr.nims.go.jp/datasets/73c9765a-2934-4fad-8166-f85c6486991e):

| Facility | File used | Plotted as |
|---|---|---|
| SPring-8, Hokkaido Univ. | `*.txt` (Athena format, processed by the facility; `_ref` = reference) | μt |
| KEK-PF | `*.dat` (PF9809 raw data) | μt = ln(I0/I1) (fluorescence: ΣIf/I0) |
| Aichi SR | `*.dat` (PF9809, I0/I1/I2) | sample ln(I0/I1), reference ln(I1/I2) |
| Ritsumeikan Univ. | `*.tey`, `*.pfy`, … (normalized by the facility) and `*.dat` | as provided, and the raw ratio from `*.dat` using the formula in `metadata.yml` |
| Kyushu SR | `*.tey`, … (I/I0 processed by the facility) | I/I0 |

Spectra with more than 1,000 points (Quick XAFS) are averaged down to about 1,000 points.

Overseas databases in the IXDB tab:

| Database | Source | Plotted as |
|---|---|---|
| IHEP | `https://xasdb.ihep.ac.cn/api/spectra/<id>`, fetched by the page | μ as provided |
| LISA | the XDI file linked from IXDB | `mutrans` / `mufluor`, reference `murefer` |
| XASLIB | the raw XDI file linked from each spectrum page | `mutrans`, or ln(i0/itrans), ifluor/i0; reference ln(itrans/irefer) |
| CLS | the CLS XASDB API, using the spectrum ID kept in the IXDB index (`wid`) | μ and reference μ as provided |

Not plotted: FAME (SSHADE) requires a login to export data. ESRF ID21 data are on the ESRF website, whose [terms](https://www.esrf.fr/home/about/disclaimer-and-privacy-policy.html) prohibit reproduction without prior written authorisation (and the site does not allow direct access from the page); about half of its links are PDF/JPG.

## Deploy and update

- **GitHub Pages:** source = `main` branch, `/docs` folder.
- **Run locally:** `python -m http.server 8000 --directory docs`, then open http://localhost:8000
- **Update the IXDB index:** `python tools/build_ixdb_index.py --out docs/ixdb_index.js` (Python 3.9+, no extra packages). The first run fetches about 1,200 MatVoc pages one at a time to respect its rate limit (~1 hour) and caches them in `cache/matvoc.json`; later runs reuse the cache. Use `--no-matvoc` to skip.
- **Update the spectra for plotting:** `python tools/build_spectra.py --out docs/spectra` (needs PyYAML). It downloads the zip of each of the ~2,265 MDR XAFS DB datasets (several hundred MB in total; a few hours, as MDR often answers slowly or with 504) and skips datasets already in `docs/spectra`, so it can be re-run to fill in failures or new datasets.
- **Update the overseas spectra:** `python tools/build_overseas_spectra.py --index docs/ixdb_index.js --out docs/spectra` (after updating the IXDB index; ~1,100 spectra from LISA, XASLIB and CLS; skips existing files).
- **Update the reference energies:** `python tools/build_reference_energies.py --out docs/spectra/refenergies.json` (needs `xraydb`; fetches the NIST tables).
- **Update the XANES matching index:** `python tools/build_xanes_index.py --spectra docs/spectra --index docs/ixdb_index.js` (needs `xraydb`; run after the spectra are updated; reads local files only, ~2 min).
- **Update the HAXPES spectra:** `python tools/build_haxpes_spectra.py --out docs/spectra` (37 datasets, one at a time).

## Limitations

- MDR responds slowly: opening a DOI or starting a zip download can take 30 s to 1 min.
- Plots are only available for spectra imported so far (prototype; the footer shows the current counts): the MDR XAFS DB import is in progress, and 18 of the 693 CLS spectra are no longer in CLS. Re-run the build scripts to fill in the rest.
- Element highlighting in the MDR tabs reflects registrations as of 2026-10-22; other elements can still be searched.
- MatVoc names and links reflect the time the index was built; materials without a MatVoc entry (or without formula/links there) show the record title only.
- Prototype: information shown is based on the metadata registered in each database.

## License and data sources

- **Code** (`docs/index.html`, `tools/`): [MIT License](LICENSE)
- **IXDB index** (`docs/ixdb_index.js`): derived from M. Ishii et al., "International XAFS DB RDF and Ontology" (NIMS MDR, [doi:10.48505/nims.5513](https://doi.org/10.48505/nims.5513), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)). Facility information for MDR records is taken from DataCite metadata (CC0). Material names, formulas and related links are taken from [MatVoc](https://matvoc.nims.go.jp/explore/) (NIMS Materials Data Platform); follow NIMS's terms of use.
- **Spectra for plotting** (`docs/spectra/`): extracted (and thinned out) from the datasets of MDR XAFS DB ([doi:10.48505/nims.1447](https://doi.org/10.48505/nims.1447)). Each file keeps the license of its dataset (CC BY 4.0 or CC BY-NC-SA 4.0, as shown on the dataset page); not covered by the MIT License.
- **HAXPES spectra for plotting** (`docs/spectra/haxpes/`): from MDR HAXPES DB; CC BY-NC-SA 4.0 (as stated in each dataset's metadata). Not covered by the MIT License.
- **Overseas spectra for plotting** (`docs/spectra/lisa/`, `xaslib/`, `cls/`): extracted (and thinned out) from LISA XAS Database, XASLIB and CLS XAS Database; they keep each database's terms. Not covered by the MIT License.
  - LISA XAS Database: CC BY 4.0 (A. Puri, [doi:10.5281/zenodo.10778068](https://doi.org/10.5281/zenodo.10778068))
  - XASLIB: public domain ("can be used for any purpose, without restrictions", [about page](https://xaslib.xrayabsorption.org/about))
  - CLS XAS Database: CC BY 4.0 (stated in each spectrum; kept in each file as `lic`) Other spectral data are not included in this repository.
- Follow the terms of use and citation rules of each database:
  - MDR XAFS DB: [doi:10.48505/nims.1447](https://doi.org/10.48505/nims.1447) (data provided by JASRI: CC BY 4.0; for SPring-8 BL14B2 data also cite Ofuchi, Matsumoto, Honma, *Radiat. Phys. Chem.* **218** (2024) 111581)
  - MDR HAXPES DB: [doi:10.48505/nims.3056](https://doi.org/10.48505/nims.3056)
  - International XAFS DB Portal: M. Ishii et al., *J. Synchrotron Rad.* **32** (2025), [doi:10.1107/S1600577525002206](https://doi.org/10.1107/S1600577525002206)

## Author

Takahiro Matsumoto / JASRI (Japan Synchrotron Radiation Research Institute)
