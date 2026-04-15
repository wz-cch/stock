"""
台股技術指標 + 籌碼分析工具 (v2.0)
用法：python tw_stock_analyzer.py
需要安裝：pip install yfinance pandas pandas-ta requests beautifulsoup4 openpyxl
"""

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
from datetime import datetime, timedelta
import os

# ============================================================
# ✏️  設定區：改這裡就好
# ============================================================
STOCKS_FILE = "stocks.txt"  # 追蹤清單（每行一個代號，# 開頭為註解）
PERIOD      = "1y"          # 抓多久的K線："6mo" / "1y" / "2y"
OUTPUT_DIR  = "data"        # 根輸出目錄（每支股票建立子資料夾）
# ============================================================

def _load_stock_ids(filepath: str) -> list:
    """讀取 stocks.txt，回傳代號清單（自動處理 .TW 後綴）"""
    ids = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 移除 .TW / .tw 後綴，程式內部統一用純代號
                sid = line.upper().removesuffix(".TW")
                ids.append(sid)
    except FileNotFoundError:
        print(f"⚠️  找不到 {filepath}，請建立追蹤清單")
    return ids

def fetch_price_data(stock_id: str, period: str) -> pd.DataFrame:
    """從 Yahoo Finance 抓股價 K 線"""
    ticker = f"{stock_id}.TW"
    print(f"📡 正在抓取 {ticker} 股價資料...")
    df = yf.download(ticker, period=period, auto_adjust=True)
    if df.empty:
        raise ValueError(f"找不到股票 {ticker}，請確認代號是否正確")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.index.name = "Date"
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["開盤", "最高", "最低", "收盤", "成交量"]
    for col in ["開盤", "最高", "最低", "收盤"]:
        df[col] = df[col].round(2)
    # Yahoo Finance 成交量單位為「股」，換算成「張」(1張=1000股) 與法人、融資券欄位一致
    df["成交量"] = (df["成交量"] / 1000).round(0).astype("Int64")
    print(f"  ✅ 取得 {len(df)} 筆 K 線資料（{df.index[0].date()} ~ {df.index[-1].date()}）")
    return df

def fetch_chip_data(stock_id: str, start_date: str) -> pd.DataFrame:
    """
    抓取三大法人買賣超 (FinMind API)
    dataset: TaiwanStockInstitutionalInvestorsBuySell
    回傳欄位：外資買賣超、投信買賣超、自營商買賣超、法人合計
    """
    print("📡 抓取籌碼數據（FinMind API）...")
    # 名稱對應表
    name_map = {
        "Foreign_Investor":       "外資買賣超",
        "Investment_Trust":       "投信買賣超",
        "Dealer":                 "自營商買賣超",
        "Dealer_self":            "自營商買賣超",   # 部分日期使用此名稱
    }
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset":    "TaiwanStockInstitutionalInvestorsBuySell",
                "data_id":    stock_id,
                "start_date": start_date,
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        payload = r.json()

        if payload.get("msg") != "success" or not payload.get("data"):
            raise ValueError(f"FinMind 回傳異常：{payload.get('msg')}")

        # 每列為單一法人單日資料，pivot 成日期為 index
        rows = []
        for item in payload["data"]:
            col = name_map.get(item["name"])
            if col is None:
                continue
            rows.append({
                "Date": item["date"],
                "col":  col,
                "net":  item["buy"] - item["sell"],
            })

        df_raw = pd.DataFrame(rows)
        df_chip = df_raw.pivot_table(index="Date", columns="col", values="net", aggfunc="sum")
        df_chip.index = pd.to_datetime(df_chip.index)

        # 確保三欄都存在
        for col in ["外資買賣超", "投信買賣超", "自營商買賣超"]:
            if col not in df_chip.columns:
                df_chip[col] = 0

        # 單位由股換算成張（÷1000）
        for col in ["外資買賣超", "投信買賣超", "自營商買賣超"]:
            df_chip[col] = (df_chip[col] / 1000).round(0)

        df_chip["法人合計"] = (
            df_chip["外資買賣超"] +
            df_chip["投信買賣超"] +
            df_chip["自營商買賣超"]
        )
        df_chip.columns.name = None
        print(f"  ✅ 取得 {len(df_chip)} 筆籌碼數據")
        return df_chip

    except Exception as e:
        print(f"  ⚠️  籌碼抓取失敗：{e}")
        return pd.DataFrame()

def fetch_margin_data(stock_id: str, start_date: str) -> pd.DataFrame:
    """
    抓取融資融券（FinMind API）
    dataset: TaiwanStockMarginPurchaseShortSale
    回傳欄位：融資餘額、融券餘額、融資買進、融券賣出（單位：張）
    """
    print("📡 抓取融資融券數據（FinMind API）...")
    col_map = {
        "MarginPurchaseTodayBalance": "融資餘額",
        "ShortSaleTodayBalance":      "融券餘額",
        "MarginPurchaseBuy":          "融資買進",
        "ShortSaleSell":              "融券賣出",
    }
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset":    "TaiwanStockMarginPurchaseShortSale",
                "data_id":    stock_id,
                "start_date": start_date,
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        payload = r.json()

        if payload.get("msg") != "success" or not payload.get("data"):
            raise ValueError(f"FinMind 回傳異常：{payload.get('msg')}")

        rows = []
        for item in payload["data"]:
            row = {"Date": item["date"]}
            for api_key, col_name in col_map.items():
                row[col_name] = item.get(api_key, 0)
            rows.append(row)

        df_margin = pd.DataFrame(rows).drop_duplicates("Date")
        df_margin.index = pd.to_datetime(df_margin["Date"])
        df_margin = df_margin.drop(columns=["Date"])
        df_margin.index.name = None

        for col in col_map.values():
            df_margin[col] = df_margin[col].astype("Int64")

        print(f"  ✅ 取得 {len(df_margin)} 筆融資融券數據")
        return df_margin

    except Exception as e:
        print(f"  ⚠️  融資融券抓取失敗：{e}")
        return pd.DataFrame()

def fetch_monthly_revenue(stock_id: str) -> pd.DataFrame:
    """抓月營收（FinMind API），自行計算年增率與月增率"""
    print("📡 抓取月營收資料（FinMind API）...")
    start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://api.finmindtrade.com/api/v4/data",
            params={
                "dataset":    "TaiwanStockMonthRevenue",
                "data_id":    stock_id,
                "start_date": start_date,
            },
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("msg") != "success" or not payload.get("data"):
            raise ValueError(f"FinMind 回傳異常：{payload.get('msg')}")

        records = []
        for row in payload["data"]:
            records.append({
                "年月":         f"{row['revenue_year']}/{row['revenue_month']:02d}",
                "_year":        row["revenue_year"],
                "_month":       row["revenue_month"],
                "月營收(千元)": round(row.get("revenue", 0) / 1000),
            })
        df = pd.DataFrame(records).drop_duplicates("年月").sort_values("年月").reset_index(drop=True)

        # 自行計算年增率與月增率（API 未提供）
        rev_lookup = {(r["_year"], r["_month"]): r["月營收(千元)"] for _, r in df.iterrows()}
        yoy_list, mom_list = [], []
        for _, row in df.iterrows():
            y, m = row["_year"], row["_month"]
            prev_year = rev_lookup.get((y - 1, m))
            prev_month = rev_lookup.get((y, m - 1) if m > 1 else (y - 1, 12))
            cur = row["月營收(千元)"]
            yoy_list.append(round((cur / prev_year - 1) * 100, 2) if prev_year else None)
            mom_list.append(round((cur / prev_month - 1) * 100, 2) if prev_month else None)

        df["年增率(%)"] = yoy_list
        df["月增率(%)"] = mom_list
        df = df.drop(columns=["_year", "_month"])
        print(f"  ✅ 取得 {len(df)} 筆月營收（FinMind）")
        return df
    except Exception as e:
        print(f"  ⚠️  月營收抓取失敗：{e}")
        return pd.DataFrame()

def fetch_shareholder_dist(stock_id: str) -> pd.DataFrame:
    """
    抓 TDCC 股權分散表週歷史資料（約一年），計算每週大戶與散戶持股比
    大戶：400 張以上（分級 12~15）
    散戶：10 張以下（分級 1~3，< 10,000 股）
    回傳 DataFrame，index=日期(str 'YYYY-MM-DD')，欄位：
        大戶持股比(%)、散戶持股比(%)、大戶人數、散戶人數
    """
    print("📡 抓取股權分散週資料（TDCC 網站）...")
    try:
        from bs4 import BeautifulSoup

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock",
        })
        QRYURL = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"

        def _get_token_and_dates():
            r = session.get(QRYURL, timeout=15)
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")
            tok = s.find("input", {"name": "SYNCHRONIZER_TOKEN"})["value"]
            sel = s.find("select", {"name": "scaDate"})
            dates = [o.get("value") for o in sel.find_all("option") if o.get("value")]
            return tok, dates

        _, all_dates = _get_token_and_dates()

        def _query_week(date_str):
            """查詢單週，回傳 dict 或 None；每次重取 token"""
            tok, _ = _get_token_and_dates()
            r2 = session.post(
                QRYURL,
                data={
                    "SYNCHRONIZER_TOKEN": tok,
                    "SYNCHRONIZER_URI":   "/portal/zh/smWeb/qryStock",
                    "method":    "submit",
                    "firDate":   date_str,
                    "scaDate":   date_str,
                    "sqlMethod": "StockNo",
                    "stockNo":   stock_id,
                    "stockName": "",
                },
                timeout=15,
            )
            soup2 = BeautifulSoup(r2.text, "html.parser")
            tables = soup2.find_all("table")
            if len(tables) < 2:
                return None
            big_pct = 0.0; small_pct = 0.0
            big_cnt = 0;   small_cnt = 0
            for row in tables[1].find_all("tr")[1:]:
                cells = [td.text.strip().replace(",", "") for td in row.find_all("td")]
                if len(cells) < 5 or not cells[0].isdigit():
                    continue
                lvl = int(cells[0])
                pct = float(cells[4])
                cnt = int(cells[2]) if cells[2].isdigit() else 0
                if 12 <= lvl <= 15:      # 大戶：400張以上
                    big_pct += pct
                    big_cnt += cnt
                elif 1 <= lvl <= 3:      # 散戶：10張以下
                    small_pct += pct
                    small_cnt += cnt
            return {
                "大戶持股比(%)": round(big_pct, 2),
                "散戶持股比(%)": round(small_pct, 2),
                "大戶人數":      big_cnt,
                "散戶人數":      small_cnt,
            }

        records = []
        for d in sorted(all_dates):
            row = _query_week(d)
            if row:
                date_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                records.append({"日期": date_fmt, **row})

        df_s = pd.DataFrame(records).set_index("日期")
        print(f"  ✅ 取得 {len(df_s)} 週的股權分散資料")
        return df_s
    except Exception as e:
        print(f"  ⚠️  股權分散抓取失敗：{e}")
        return pd.DataFrame()

def calc_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """計算技術指標 + 籌碼訊號"""
    print("🔢 計算技術指標與籌碼訊號...")
    c = df["收盤"]
    h = df["最高"]
    l = df["最低"]
    v = df["成交量"]

    # ── 均線 ──────────────────────────────────────────────
    df["MA5"]  = c.rolling(5).mean().round(2)
    df["MA10"] = c.rolling(10).mean().round(2)
    df["MA20"] = c.rolling(20).mean().round(2)
    df["MA60"] = c.rolling(60).mean().round(2)

    # ── 均量 ──────────────────────────────────────────────
    df["Vol_MA5"]  = v.rolling(5).mean().round(0).astype("Int64")
    df["Vol_MA20"] = v.rolling(20).mean().round(0).astype("Int64")

    # ── MACD ────────────────────────────────────────────
    macd = ta.macd(c, fast=12, slow=26, signal=9)
    df["MACD"]        = macd["MACD_12_26_9"].round(2)
    df["MACD_Signal"] = macd["MACDs_12_26_9"].round(2)
    df["MACD_Hist"]   = macd["MACDh_12_26_9"].round(2)

    # ── KD ──────────────────────────────────────────────
    stoch = ta.stoch(h, l, c, k=9, d=3, smooth_k=3)
    df["K值"] = stoch[f"STOCHk_9_3_3"].round(2)
    df["D值"] = stoch[f"STOCHd_9_3_3"].round(2)

    # ── RSI ─────────────────────────────────────────────
    df["RSI14"] = ta.rsi(c, length=14).round(2)

    # ── 布林通道 ────────────────────────────────────────
    bb = ta.bbands(c, length=20, std=2)
    _bbu = next(col for col in bb.columns if col.startswith("BBU"))
    _bbm = next(col for col in bb.columns if col.startswith("BBM"))
    _bbl = next(col for col in bb.columns if col.startswith("BBL"))
    _bbp = next(col for col in bb.columns if col.startswith("BBP"))
    df["BB_Upper"] = bb[_bbu].round(2)
    df["BB_Mid"]   = bb[_bbm].round(2)
    df["BB_Lower"] = bb[_bbl].round(2)
    df["BB_%B"]    = bb[_bbp].round(4)

    # ── 乖離率 ────────────────────────────────────────────
    df["BIAS5"]  = ((c - df["MA5"])  / df["MA5"]  * 100).round(2)
    df["BIAS20"] = ((c - df["MA20"]) / df["MA20"] * 100).round(2)
    df["量比"] = (v / df["Vol_MA5"]).round(2)

    # ── 綜合訊號判斷（含籌碼） ──────────────────────────────
    signals = []
    for i in range(len(df)):
        s = []
        row = df.iloc[i]
        
        # 技術面訊號
        if pd.notna(row["MACD"]) and pd.notna(row["MACD_Signal"]):
            s.append("MACD多頭" if row["MACD"] > row["MACD_Signal"] else "MACD空頭")
        if pd.notna(row["K值"]) and pd.notna(row["D值"]):
            if row["K值"] > row["D值"] and row["K值"] < 80: s.append("KD金叉")
            elif row["K值"] < row["D值"] and row["K值"] > 20: s.append("KD死叉")
            if row["K值"] > 80: s.append("KD超買")
            if row["K值"] < 20: s.append("KD超賣")
        if pd.notna(row["RSI14"]):
            if row["RSI14"] > 70: s.append("RSI超買")
            if row["RSI14"] < 30: s.append("RSI超賣")

        # 籌碼面訊號 (只有當籌碼數據存在時)
        if "法人合計" in row and pd.notna(row["法人合計"]):
            if row["法人合計"] > 5000: s.append("法人強勢買超")
            elif row["法人合計"] < -5000: s.append("法人強勢賣超")
            
            if "外資買賣超" in row and "投信買賣超" in row:
                if row["外資買賣超"] > 0 and row["投信買賣超"] > 0:
                    s.append("外投同步買進")
                elif row["外資買賣超"] < 0 and row["投信買賣超"] < 0:
                    s.append("外投同步拋售")

        signals.append(" | ".join(s) if s else "")

    df["訊號"] = signals
    print("  ✅ 技術指標與籌碼訊號計算完成")
    return df

def print_latest_summary(df: pd.DataFrame, stock_id: str):
    """印出最新一日的關鍵數字"""
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    print()
    print("=" * 60)
    print(f"  📊  {stock_id} 綜合分析摘要（{df.index[-1].date()}）")
    print("=" * 60)
    print(f"  收盤價   : {latest['收盤']:.1f}  (昨 {prev['收盤']:.1f})")
    print(f"  MA5/10/20: {latest['MA5']} / {latest['MA10']} / {latest['MA20']}")
    print(f"  乖離MA20 : {latest['BIAS20']}%")
    print(f"  量比(5日): {latest['量比']}x")
    
    if "法人合計" in df.columns:
        chip_row = df[["法人合計","外資買賣超","投信買賣超"]].dropna().iloc[-1] if not df[["法人合計","外資買賣超","投信買賣超"]].dropna().empty else None
        if chip_row is not None:
            chip_date = df[["法人合計"]].dropna().index[-1].date()
            print(f"  法人合計 : {chip_row['法人合計']:,.0f} 張  ({chip_date})")
            print(f"  外資買超 : {chip_row['外資買賣超']:,.0f} 張")
            print(f"  投信買超 : {chip_row['投信買賣超']:,.0f} 張")
        else:
            print(f"  籌碼     : 今日未公布")

    margin_cols = ["融資餘額", "融券餘額", "融資買進", "融券賣出"]
    if all(c in df.columns for c in margin_cols):
        m_df = df[margin_cols].dropna()
        if not m_df.empty:
            m_row = m_df.iloc[-1]
            m_date = m_df.index[-1].date()
            print(f"  ────────────────────────────────────────")
            print(f"  融資餘額 : {m_row['融資餘額']:,.0f} 張  ({m_date})")
            print(f"  融券餘額 : {m_row['融券餘額']:,.0f} 張")
            print(f"  融資買進 : {m_row['融資買進']:,.0f} 張（今日）")
            print(f"  融券賣出 : {m_row['融券賣出']:,.0f} 張（今日）")
        else:
            print(f"  融資券   : 今日未公布")

    print(f"  綜合訊號 : {latest['訊號'] or '無特別訊號'}")
    print("=" * 60)

def save_outputs(df: pd.DataFrame, rev_df: pd.DataFrame, stock_id: str, shareholder_df: pd.DataFrame = None, output_dir: str = None) -> str:
    """存成 CSV（同日/同月重跑會覆蓋）"""
    if output_dir is None:
        output_dir = OUTPUT_DIR
    today = datetime.now().strftime("%Y%m%d")
    month = datetime.now().strftime("%Y%m")
    name = f"{stock_id}_綜合分析_{today}.csv"
    path = os.path.join(output_dir, name)

    df_out = df.copy()
    df_out.index = df_out.index.strftime("%Y-%m-%d")
    df_out.index.name = "日期"
    # 輸出時加上單位，保持內部欄位名稱不變
    df_out = df_out.rename(columns={
        "開盤":       "開盤(元)",
        "最高":       "最高(元)",
        "最低":       "最低(元)",
        "收盤":       "收盤(元)",
        "成交量":     "成交量(張)",
        "外資買賣超": "外資買賣超(張)",
        "投信買賣超": "投信買賣超(張)",
        "自營商買賣超": "自營商買賣超(張)",
        "法人合計":   "法人合計(張)",
        "融資餘額":   "融資餘額(張)",
        "融券餘額":   "融券餘額(張)",
        "融資買進":   "融資買進(張)",
        "融券賣出":   "融券賣出(張)",
        "MA5":        "MA5(元)",
        "MA10":       "MA10(元)",
        "MA20":       "MA20(元)",
        "MA60":       "MA60(元)",
        "Vol_MA5":    "Vol_MA5(張)",
        "Vol_MA20":   "Vol_MA20(張)",
        "MACD":       "MACD(元)",
        "MACD_Signal":"MACD_Signal(元)",
        "MACD_Hist":  "MACD_Hist(元)",
        "K值":        "K值(%)",
        "D值":        "D值(%)",
        "RSI14":      "RSI14(%)",
        "BB_Upper":   "BB_Upper(元)",
        "BB_Mid":     "BB_Mid(元)",
        "BB_Lower":   "BB_Lower(元)",
        "BB_%B":      "BB_%B(%)",
        "BIAS5":      "BIAS5(%)",
        "BIAS20":     "BIAS20(%)",
        "量比":       "量比(倍)",
    })
    df_out.to_csv(path, encoding="utf-8-sig")
    print(f"\n  💾 綜合分析 CSV（含籌碼）：{path}")

    if not rev_df.empty:
        rev_name = f"{stock_id}_月營收_{month}.csv"
        rev_path = os.path.join(output_dir, rev_name)
        rev_out = rev_df.copy()
        rev_out.to_csv(rev_path, index=False, encoding="utf-8-sig")
        print(f"  💾 月營收 CSV  ：{rev_path}")

    # 股權分散週資料獨立 CSV（每月覆蓋）
    if shareholder_df is not None and not shareholder_df.empty:
        sh_name = f"{stock_id}_股權分散_{month}.csv"
        sh_path = os.path.join(output_dir, sh_name)
        shareholder_df.to_csv(sh_path, encoding="utf-8-sig")
        print(f"  💾 股權分散 CSV：{sh_path}")

    return path

def main():
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║      台股技術 + 籌碼綜合分析工具 v2.0       ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    stock_ids = _load_stock_ids(STOCKS_FILE)
    if not stock_ids:
        print("❌ 追蹤清單為空，請在 stocks.txt 中加入股票代號")
        return

    print(f"📋 追蹤清單：{', '.join(stock_ids)}（共 {len(stock_ids)} 支）")
    print()

    for stock_id in stock_ids:
        # 每支股票建立獨立子資料夾
        stock_dir = os.path.join(OUTPUT_DIR, stock_id)
        os.makedirs(stock_dir, exist_ok=True)

        print(f"{'='*60}")
        print(f"  處理中：{stock_id}")
        print(f"{'='*60}")

        try:
            # 1. 抓股價
            df = fetch_price_data(stock_id, PERIOD)

            # 2. 抓籌碼
            start_date = df.index[0].strftime("%Y-%m-%d")
            chip_df = fetch_chip_data(stock_id, start_date)

            # 3. 合併籌碼數據 (Left Join)
            if not chip_df.empty:
                df = df.merge(chip_df, left_index=True, right_index=True, how="left")

            # 3b. 抓融資融券並合併
            margin_df = fetch_margin_data(stock_id, start_date)
            if not margin_df.empty:
                df = df.merge(margin_df, left_index=True, right_index=True, how="left")

            # 4. 計算指標
            df = calc_technical_indicators(df)

            # 5. 抓月營收（ETF 無此資料，空 DataFrame 時跳過）
            rev_df = fetch_monthly_revenue(stock_id)

            # 6. 抓股權分散週資料（TDCC，約一年）
            shareholder_df = fetch_shareholder_dist(stock_id)

            print_latest_summary(df, stock_id)
            save_outputs(df, rev_df, stock_id, shareholder_df, output_dir=stock_dir)

        except Exception as e:
            print(f"  ❌ {stock_id} 處理失敗：{e}")

        print()

    print("✅ 全部完成！")

if __name__ == "__main__":
    main()