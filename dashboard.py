"""
台股分析看板 - Streamlit Dashboard
執行：streamlit run dashboard.py
"""

import os
import glob
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── 頁面設定 ────────────────────────────────────────────────
st.set_page_config(
    page_title="台股分析看板",
    page_icon="📊",
    layout="wide",
)

DATA_DIR    = "data"
STOCKS_FILE = "stocks.txt"

# ── 工具函數 ─────────────────────────────────────────────────

def load_stock_map(filepath: str) -> dict:
    """讀取 stocks.txt，回傳 {代號: 名稱}"""
    result = {}
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(None, 1)
                sid  = parts[0].upper().removesuffix(".TW")
                name = parts[1].strip() if len(parts) > 1 else sid
                result[sid] = name
    except FileNotFoundError:
        pass
    # 也掃描 data/ 下有資料夾但不在 stocks.txt 的代號
    if os.path.isdir(DATA_DIR):
        for d in sorted(os.listdir(DATA_DIR)):
            if os.path.isdir(os.path.join(DATA_DIR, d)) and d not in result:
                result[d] = d
    return result

@st.cache_data(ttl=300)
def load_analysis(stock_id: str) -> pd.DataFrame:
    pattern = os.path.join(DATA_DIR, stock_id, f"{stock_id}_綜合分析_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    df = pd.read_csv(files[-1], index_col="日期", parse_dates=True)
    return df

@st.cache_data(ttl=300)
def load_revenue(stock_id: str) -> pd.DataFrame:
    pattern = os.path.join(DATA_DIR, stock_id, f"{stock_id}_月營收_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    return pd.read_csv(files[-1])

@st.cache_data(ttl=300)
def load_shareholder(stock_id: str) -> pd.DataFrame:
    pattern = os.path.join(DATA_DIR, stock_id, f"{stock_id}_股權分散_*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        return pd.DataFrame()
    return pd.read_csv(files[-1], index_col="日期", parse_dates=True)

def col(df, *names):
    """回傳 df 中第一個存在的欄位名稱"""
    for n in names:
        if n in df.columns:
            return n
    return None

# ── 側邊欄 ───────────────────────────────────────────────────
stock_map = load_stock_map(STOCKS_FILE)
if not stock_map:
    st.error("找不到追蹤清單或 data/ 資料夾，請先執行 tw_stock_analyzer.py")
    st.stop()

options = {f"{name} ({sid})": sid for sid, name in stock_map.items()}
with st.sidebar:
    st.title("📊 台股分析看板")
    selected_label = st.selectbox("選擇股票", list(options.keys()))
    stock_id   = options[selected_label]
    stock_name = stock_map[stock_id]

    st.divider()
    days = st.slider("顯示天數", min_value=30, max_value=365, value=90, step=10)
    st.caption(f"資料來自 data/{stock_id}/")

# ── 讀取資料 ─────────────────────────────────────────────────
df   = load_analysis(stock_id)
rev  = load_revenue(stock_id)
sh   = load_shareholder(stock_id)

if df.empty:
    st.warning(f"找不到 {stock_id} 的分析資料，請先執行 tw_stock_analyzer.py")
    st.stop()

df_show = df.iloc[-days:]

# ── 標題列 ───────────────────────────────────────────────────
latest = df_show.iloc[-1]
prev   = df_show.iloc[-2]
close_col = col(df, "收盤(元)", "收盤")
chg = latest[close_col] - prev[close_col]
chg_pct = chg / prev[close_col] * 100

st.title(f"{stock_name}　({stock_id})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("收盤價", f"{latest[close_col]:.1f}", f"{chg:+.1f} ({chg_pct:+.2f}%)")

rsi_col = col(df, "RSI14(%)", "RSI14")
if rsi_col:
    c2.metric("RSI14", f"{latest[rsi_col]:.1f}")

k_col = col(df, "K值(%)", "K值")
if k_col:
    c3.metric("K 值", f"{latest[k_col]:.1f}")

chip_col = col(df, "法人合計(張)", "法人合計")
if chip_col and pd.notna(latest.get(chip_col)):
    c4.metric("法人合計", f"{latest[chip_col]:,.0f} 張")

st.divider()

# ─────────────────────────────────────────────────────────────
# 圖1：K 線 + 布林通道 + 均線
# ─────────────────────────────────────────────────────────────
st.subheader("📈 K 線 + 布林通道 + 均線")

o_col  = col(df, "開盤(元)", "開盤")
h_col  = col(df, "最高(元)", "最高")
l_col  = col(df, "最低(元)", "最低")
bbu    = col(df, "BB_Upper(元)", "BB_Upper")
bbm    = col(df, "BB_Mid(元)",   "BB_Mid")
bbl    = col(df, "BB_Lower(元)", "BB_Lower")
ma5    = col(df, "MA5(元)",  "MA5")
ma20   = col(df, "MA20(元)", "MA20")
ma60   = col(df, "MA60(元)", "MA60")

fig1 = go.Figure()
fig1.add_trace(go.Candlestick(
    x=df_show.index, open=df_show[o_col], high=df_show[h_col],
    low=df_show[l_col], close=df_show[close_col],
    name="K線", increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
))
if bbu:
    fig1.add_trace(go.Scatter(x=df_show.index, y=df_show[bbu], name="BB上軌",
        line=dict(color="rgba(255,165,0,0.5)", dash="dot"), showlegend=True))
    fig1.add_trace(go.Scatter(x=df_show.index, y=df_show[bbl], name="BB下軌",
        line=dict(color="rgba(255,165,0,0.5)", dash="dot"),
        fill="tonexty", fillcolor="rgba(255,165,0,0.05)", showlegend=True))
if bbm:
    fig1.add_trace(go.Scatter(x=df_show.index, y=df_show[bbm], name="BB中軌",
        line=dict(color="rgba(255,165,0,0.8)", dash="dash")))
for ma_col, color, label in [(ma5, "#ff9800", "MA5"), (ma20, "#2196F3", "MA20"), (ma60, "#9C27B0", "MA60")]:
    if ma_col:
        fig1.add_trace(go.Scatter(x=df_show.index, y=df_show[ma_col], name=label,
            line=dict(color=color, width=1.2)))
fig1.update_layout(height=420, xaxis_rangeslider_visible=False, margin=dict(t=20, b=20))
st.plotly_chart(fig1, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 圖2：成交量
# ─────────────────────────────────────────────────────────────
st.subheader("📊 成交量")
vol_col   = col(df, "成交量(張)",  "成交量")
vma5_col  = col(df, "Vol_MA5(張)", "Vol_MA5")
vma20_col = col(df, "Vol_MA20(張)","Vol_MA20")

if vol_col:
    colors = ["#ef5350" if df_show[close_col].iloc[i] >= df_show[close_col].iloc[i-1]
              else "#26a69a" for i in range(len(df_show))]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=df_show.index, y=df_show[vol_col], name="成交量",
        marker_color=colors, opacity=0.7))
    if vma5_col:
        fig2.add_trace(go.Scatter(x=df_show.index, y=df_show[vma5_col], name="Vol MA5",
            line=dict(color="#ff9800", width=1.2)))
    if vma20_col:
        fig2.add_trace(go.Scatter(x=df_show.index, y=df_show[vma20_col], name="Vol MA20",
            line=dict(color="#2196F3", width=1.2)))
    fig2.update_layout(height=220, margin=dict(t=20, b=20))
    st.plotly_chart(fig2, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 圖3：MACD
# ─────────────────────────────────────────────────────────────
st.subheader("📉 MACD")
macd_col = col(df, "MACD(元)",        "MACD")
sig_col  = col(df, "MACD_Signal(元)", "MACD_Signal")
hist_col = col(df, "MACD_Hist(元)",   "MACD_Hist")

if macd_col:
    fig3 = go.Figure()
    if hist_col:
        hist_colors = ["#ef5350" if v >= 0 else "#26a69a" for v in df_show[hist_col].fillna(0)]
        fig3.add_trace(go.Bar(x=df_show.index, y=df_show[hist_col], name="MACD Hist",
            marker_color=hist_colors, opacity=0.6))
    fig3.add_trace(go.Scatter(x=df_show.index, y=df_show[macd_col], name="MACD",
        line=dict(color="#2196F3", width=1.5)))
    if sig_col:
        fig3.add_trace(go.Scatter(x=df_show.index, y=df_show[sig_col], name="Signal",
            line=dict(color="#ff9800", width=1.5)))
    fig3.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    fig3.update_layout(height=220, margin=dict(t=20, b=20))
    st.plotly_chart(fig3, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 圖4：KD + RSI
# ─────────────────────────────────────────────────────────────
st.subheader("🔄 KD / RSI")
k_col2 = col(df, "K值(%)", "K值")
d_col  = col(df, "D值(%)", "D值")

if k_col2 or rsi_col:
    fig4 = make_subplots(rows=1, cols=2, subplot_titles=("KD", "RSI14"))
    if k_col2:
        fig4.add_trace(go.Scatter(x=df_show.index, y=df_show[k_col2], name="K",
            line=dict(color="#2196F3")), row=1, col=1)
    if d_col:
        fig4.add_trace(go.Scatter(x=df_show.index, y=df_show[d_col], name="D",
            line=dict(color="#ff9800")), row=1, col=1)
    if rsi_col:
        fig4.add_trace(go.Scatter(x=df_show.index, y=df_show[rsi_col], name="RSI14",
            line=dict(color="#9C27B0")), row=1, col=2)
    for y_val in [20, 80]:
        fig4.add_hline(y=y_val, line_dash="dash", line_color="gray", opacity=0.4, row=1, col=1)
    for y_val in [30, 70]:
        fig4.add_hline(y=y_val, line_dash="dash", line_color="gray", opacity=0.4, row=1, col=2)
    fig4.update_layout(height=260, margin=dict(t=40, b=20))
    st.plotly_chart(fig4, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 圖5：三大法人 + 融資/融券餘額
# ─────────────────────────────────────────────────────────────
st.subheader("🏦 法人買賣超 + 融資融券")
fi_col  = col(df, "外資買賣超(張)",    "外資買賣超")
it_col  = col(df, "投信買賣超(張)",    "投信買賣超")
dl_col  = col(df, "自營商買賣超(張)",  "自營商買賣超")
mb_col  = col(df, "融資餘額(張)",      "融資餘額")
ss_col  = col(df, "融券餘額(張)",      "融券餘額")

if fi_col or mb_col:
    fig5 = make_subplots(rows=1, cols=2,
        subplot_titles=("三大法人買賣超（張）", "融資餘額 / 融券餘額（張）"))
    if fi_col:
        fig5.add_trace(go.Bar(x=df_show.index, y=df_show[fi_col], name="外資",
            marker_color="#2196F3", opacity=0.8), row=1, col=1)
    if it_col:
        fig5.add_trace(go.Bar(x=df_show.index, y=df_show[it_col], name="投信",
            marker_color="#ff9800", opacity=0.8), row=1, col=1)
    if dl_col:
        fig5.add_trace(go.Bar(x=df_show.index, y=df_show[dl_col], name="自營",
            marker_color="#9C27B0", opacity=0.8), row=1, col=1)
    if mb_col:
        fig5.add_trace(go.Scatter(x=df_show.index, y=df_show[mb_col], name="融資餘額",
            line=dict(color="#ef5350", width=1.8)), row=1, col=2)
    if ss_col:
        fig5.add_trace(go.Scatter(x=df_show.index, y=df_show[ss_col], name="融券餘額",
            line=dict(color="#26a69a", width=1.8)), row=1, col=2)
    fig5.update_layout(height=300, barmode="relative", margin=dict(t=40, b=20))
    st.plotly_chart(fig5, use_container_width=True)

# ─────────────────────────────────────────────────────────────
# 圖6：大戶/散戶持股比（週）
# ─────────────────────────────────────────────────────────────
st.subheader("👥 大戶 / 散戶持股比（週）")
if not sh.empty:
    sh_show = sh.iloc[-max(52, days//5):]
    fig6 = go.Figure()
    if "大戶持股比(%)" in sh.columns:
        fig6.add_trace(go.Scatter(x=sh_show.index, y=sh_show["大戶持股比(%)"],
            name="大戶持股比(%)", line=dict(color="#ef5350", width=2)))
    if "散戶持股比(%)" in sh.columns:
        fig6.add_trace(go.Scatter(x=sh_show.index, y=sh_show["散戶持股比(%)"],
            name="散戶持股比(%)", line=dict(color="#26a69a", width=2)))
    fig6.update_layout(height=260, yaxis_title="%", margin=dict(t=20, b=20))
    st.plotly_chart(fig6, use_container_width=True)
else:
    st.info("尚無股權分散週資料")

# ─────────────────────────────────────────────────────────────
# 圖7：月營收 + 年增率
# ─────────────────────────────────────────────────────────────
st.subheader("📅 月營收 + 年增率")
if not rev.empty and "月營收(千元)" in rev.columns:
    rev_show = rev.tail(24)
    fig7 = make_subplots(specs=[[{"secondary_y": True}]])
    fig7.add_trace(go.Bar(x=rev_show["年月"], y=rev_show["月營收(千元)"],
        name="月營收（千元）", marker_color="#2196F3", opacity=0.75), secondary_y=False)
    if "年增率(%)" in rev_show.columns:
        yoy_colors = ["#ef5350" if v >= 0 else "#26a69a"
                      for v in rev_show["年增率(%)"].fillna(0)]
        fig7.add_trace(go.Bar(x=rev_show["年月"], y=rev_show["年增率(%)"],
            name="年增率（%）", marker_color=yoy_colors, opacity=0.6,
            width=0.4), secondary_y=True)
    fig7.update_yaxes(title_text="月營收（千元）", secondary_y=False)
    fig7.update_yaxes(title_text="年增率（%）", secondary_y=True)
    fig7.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4, secondary_y=True)
    fig7.update_layout(height=320, barmode="overlay", margin=dict(t=20, b=20))
    st.plotly_chart(fig7, use_container_width=True)
else:
    st.info("無月營收資料（ETF 不適用）")

# ─────────────────────────────────────────────────────────────
# AI 結論預留區
# ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("🤖 AI 結論")
ai_path = os.path.join(DATA_DIR, stock_id, f"{stock_id}_ai_summary.txt")
if os.path.exists(ai_path):
    with open(ai_path, encoding="utf-8") as f:
        st.markdown(f.read())
else:
    st.info("尚未產生 AI 結論。請將綜合分析 CSV 貼給 Claude/GPT 取得分析後，儲存至 "
            f"`data/{stock_id}/{stock_id}_ai_summary.txt`")
