# data/history

夜間バッチが積み上げる履歴CSV（Gitにコミットする）。
- `nikkei_ohlc.csv` … date,open,high,low,close（日経225現物）
- `nikkei_vi.csv`   … date,vi（日経平均VI・％表記）

## 初回シード
IV Rank/Percentile には過去252営業日の日経VIが必要。
初回のみ投資情報サイトから日経VIの1年分をCSVでダウンロードし、
列を `date,vi` に整えて `nikkei_vi.csv` として置く（フェーズ2-2）。
