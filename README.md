# XAFS / HAXPES 標準試料スペクトル検索（試作）

XAFS・HAXPES の標準試料データを、元素から探して、選んだものだけをダウンロードできる Web ページです。
データ本体は持たず、各データベースの公開情報（DOI 登録情報・知識グラフ）を使って検索し、各データベースへ直接リンクします。

*Reference Spectra Search (prototype): find XAFS/HAXPES reference spectra by element and download only what you need. The page is bilingual (Japanese / English).*

## できること

| タブ | 検索対象 | 主な絞り込み | 取得できるもの |
|---|---|---|---|
| **IXDB（XAFS 国際横断）** | 各国 7 データベース（MDR〔日本〕、CLS〔カナダ〕、SSHADE/FAME・ESRF〔フランス〕、XASLIB〔米国〕、LISA〔イタリア〕、IHEP〔中国〕） | データベース、MDR の施設、吸収端 | 各 DB のページ、MDR は DOI・zip |
| **MDR（XAFS）** | NIMS MDR XAFS DB（SPring-8、KEK-PF、北大、立命館、あいちSR、九州SR） | 施設、吸収端、分光結晶、分類 | DOI・zip |
| **MDR（HAXPES）** | NIMS MDR HAXPES DB（SPring-8 BL46XU） | — | DOI・zip |

- 同じ物質は複数のデータベースにまたがってまとめて表示（IXDB タブ）
- 選んだ試料はタブを切り替えても保持し、まとめて zip ダウンロード、CSV（DOI・URL 一覧）保存、引用文コピーが可能
- 右上のボタンで日本語 / English を切り替え（`?lang=en` 付きの URL は英語で開く）

## 使い方

1. タブを選ぶ
2. 周期表で元素を選ぶ
3. 一覧で試料にチェックを入れ、「ダウンロード」欄から取得する

## 仕組み

```
ブラウザ（docs/index.html：静的ページ、サーバ不要）
 ├ MDR タブ  → DataCite REST API（DOI 登録情報）をその場で検索
 └ IXDB タブ → docs/ixdb_index.js（IXDB 知識グラフから作成した索引）をページ内で検索
                 └ tools/build_ixdb_index.py で作成・更新（SPARQL ＋ DataCite、数秒）
データ本体 → 各データベース（MDR の zip、各 DB のページ）から直接取得
```

- NIMS MDR の API と IXDB の SPARQL はブラウザから直接呼べない（CORS 非対応）ため、MDR は DataCite 経由、IXDB は事前作成の索引を使っています。

## 公開・更新

- **公開**：GitHub Pages の公開元を「`main` ブランチの `/docs` フォルダ」に設定するだけで動きます。
- **ローカル確認**：`python -m http.server 8000 --directory docs` → http://localhost:8000
- **IXDB 索引の更新**：`python tools/build_ixdb_index.py --out docs/ixdb_index.js`（Python 3.9 以上、追加ライブラリ不要）

## 注意・制約

- MDR の応答が遅く、DOI からページが開くまで、または zip のダウンロード開始まで 30 秒〜1 分程度かかることがあります。
- 周期表の色付け（MDR タブ）は 2026-10-22 時点の登録状況です。色のない元素も検索できます。
- IXDB タブの物質名は各データのタイトルから整形しています（物質辞書 MatVoc の名称は未使用）。
- 試作版です。表示内容は各データベースに登録されたメタデータに基づきます。

## ライセンスとデータの出典

- **プログラム**（`docs/index.html`、`tools/`）：[MIT License](LICENSE)
- **IXDB 索引**（`docs/ixdb_index.js`）：M. Ishii et al.「International XAFS DB RDF and Ontology」（NIMS MDR、[doi:10.48505/nims.5513](https://doi.org/10.48505/nims.5513)、[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）から作成。MDR データの施設情報は DataCite のメタデータ（CC0）を利用。
- **スペクトルデータ**：このリポジトリには含みません。利用条件・引用は各データベースの規定に従ってください。
  - MDR XAFS DB：[doi:10.48505/nims.1447](https://doi.org/10.48505/nims.1447)（JASRI 提供分は CC BY 4.0。SPring-8 BL14B2 のデータは Ofuchi, Matsumoto, Honma, *Radiat. Phys. Chem.* **218** (2024) 111581 も引用）
  - MDR HAXPES DB：[doi:10.48505/nims.3056](https://doi.org/10.48505/nims.3056)
  - International XAFS DB Portal：M. Ishii et al., *J. Synchrotron Rad.* **32** (2025), [doi:10.1107/S1600577525002206](https://doi.org/10.1107/S1600577525002206)
