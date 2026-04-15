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

# ── 訊號工具 ─────────────────────────────────────────────────

_SIGNAL_COLORS = {
    "多頭": "#ef5350", "金叉": "#ef5350", "買超": "#ef5350", "買進": "#ef5350",
    "空頭": "#26a69a", "死叉": "#26a69a", "賣超": "#26a69a", "拋售": "#26a69a",
    "超買": "#e65100",
    "超賣": "#1565c0",
}

def _sig_color(tag: str) -> str:
    for kw, c in _SIGNAL_COLORS.items():
        if kw in tag:
            return c
    return "#607d8b"

def _badges_html(signal_str) -> str:
    """將 'MACD多頭 | KD金叉 | ...' 轉為彩色 badge HTML"""
    if not signal_str or pd.isna(signal_str) or str(signal_str).strip() == "":
        return '<span style="color:#888;font-size:0.85em">（無特別訊號）</span>'
    tags = [t.strip() for t in str(signal_str).split("|") if t.strip()]
    parts = []
    for tag in tags:
        c = _sig_color(tag)
        parts.append(
            f'<span style="background:{c};color:#fff;padding:3px 9px;'
            f'border-radius:12px;font-size:0.82em;margin:2px 3px;display:inline-block">'
            f'{tag}</span>'
        )
    return "".join(parts)

# 強訊號 → K線垂直標記設定 (關鍵字, 線色, 標籤)
_VLINE_SIGNALS = [
    ("KD金叉",      "rgba(239,83,80,0.65)",   "▲ KD金叉"),
    ("KD死叉",      "rgba(38,166,154,0.65)",  "▼ KD死叉"),
    ("外投同步買進", "rgba(239,83,80,0.80)",   "▲ 外投買"),
    ("外投同步拋售", "rgba(38,166,154,0.80)",  "▼ 外投拋"),
    ("強勢買超",    "rgba(239,83,80,0.50)",   "▲ 強買"),
    ("強勢賣超",    "rgba(38,166,154,0.50)",  "▼ 強賣"),
    ("RSI超買",     "rgba(230,81,0,0.60)",    "RSI超買"),
    ("RSI超賣",     "rgba(21,101,192,0.60)",  "RSI超賣"),
]

def find_latest_active_gap(df, h_col, l_col):
    """
    從全部 df 偵測最近一個尚未回補的跳空缺口。
    回傳 (gap_type, y0, y1, label) 或 None。
    'up'  = 漲缺（支撐帶，紅）
    'down'= 跌缺（壓力帶，綠）
    """
    if h_col not in df.columns or l_col not in df.columns:
        return None
    highs = df[h_col].to_numpy(dtype=float)
    lows  = df[l_col].to_numpy(dtype=float)
    n     = len(df)
    for i in range(n - 1, 0, -1):
        prev_h, prev_l = highs[i - 1], lows[i - 1]
        cur_h,  cur_l  = highs[i],     lows[i]
        if cur_l > prev_h:            # 漲缺：今最低 > 昨最高
            gap_type, y0, y1 = "up",   prev_h, cur_l
        elif cur_h < prev_l:          # 跌缺：今最高 < 昨最低
            gap_type, y0, y1 = "down", cur_h,  prev_l
        else:
            continue
        # 往後確認是否已回補
        filled = any(
            (gap_type == "up"   and lows[j]  <= y0) or
            (gap_type == "down" and highs[j] >= y1)
            for j in range(i + 1, n)
        )
        if not filled:
            diff  = y1 - y0
            label = (
                f"⬆ 支撐 {y0:.1f}–{y1:.1f} (+{diff:.1f})" if gap_type == "up"
                else f"⬇ 壓力 {y0:.1f}–{y1:.1f} (-{diff:.1f})"
            )
            return gap_type, y0, y1, label
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

    st.divider()
    st.markdown("**顯示面板**")
    _ALL_PANELS = ["K線", "成交量", "MACD", "KD/RSI", "法人", "融資券"]
    active_panels = {p for p in _ALL_PANELS if st.checkbox(p, value=True, key=f"panel_{p}")}

    # 近期訊號歷程（資料載入後填入，見下方）
    _sidebar_signal_placeholder = st.empty()

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
c1.metric("收盤價", f"{latest[close_col]:.1f}", f"{chg:+.1f} ({chg_pct:+.2f}%)", delta_color="inverse")

rsi_col = col(df, "RSI14(%)", "RSI14")
if rsi_col:
    c2.metric("RSI14", f"{latest[rsi_col]:.1f}")

k_col = col(df, "K值(%)", "K值")
if k_col:
    c3.metric("K 值", f"{latest[k_col]:.1f}")

chip_col = col(df, "法人合計(張)", "法人合計")
if chip_col and pd.notna(latest.get(chip_col)):
    c4.metric("法人合計", f"{latest[chip_col]:,.0f} 張")

# ── 今日訊號 badge ────────────────────────────────────────────
_sig_col = "訊號" if "訊號" in df.columns else None
if _sig_col:
    today_sig = latest.get(_sig_col, "")
    st.markdown(
        f'<div style="padding:6px 0 4px 0"><b>今日訊號：</b>{_badges_html(today_sig)}</div>',
        unsafe_allow_html=True,
    )
    # 側邊欄近期訊號歷程
    _sig_hist = (
        df_show[[_sig_col]]
        .loc[df_show[_sig_col].fillna("").str.strip() != ""]
        .iloc[::-1]
        .head(15)
    )
    if not _sig_hist.empty:
        lines = ["**近期訊號歷程**"]
        for date, row in _sig_hist.iterrows():
            tags = [t.strip() for t in str(row[_sig_col]).split("|") if t.strip()]
            tag_html = "".join(
                f'<span style="background:{_sig_color(t)};color:#fff;'
                f'padding:1px 6px;border-radius:8px;font-size:0.75em;margin:1px">{t}</span>'
                for t in tags
            )
            lines.append(
                f'<div style="margin-bottom:4px">'
                f'<span style="font-size:0.78em;color:#aaa">{date.strftime("%m/%d")}</span> '
                f'{tag_html}</div>'
            )
        _sidebar_signal_placeholder.markdown(
            "\n".join(lines), unsafe_allow_html=True
        )

st.divider()

# ─────────────────────────────────────────────────────────────
# 主圖：動態面板（共享x軸，sidebar 勾選開關各 row）
# ─────────────────────────────────────────────────────────────
st.subheader("📈 技術分析")

o_col     = col(df, "開盤(元)", "開盤")
h_col     = col(df, "最高(元)", "最高")
l_col     = col(df, "最低(元)", "最低")
bbu       = col(df, "BB_Upper(元)", "BB_Upper")
bbm       = col(df, "BB_Mid(元)",   "BB_Mid")
bbl       = col(df, "BB_Lower(元)", "BB_Lower")
ma5       = col(df, "MA5(元)",  "MA5")
ma20      = col(df, "MA20(元)", "MA20")
ma60      = col(df, "MA60(元)", "MA60")
vol_col   = col(df, "成交量(張)",   "成交量")
vma5_col  = col(df, "Vol_MA5(張)",  "Vol_MA5")
vma20_col = col(df, "Vol_MA20(張)", "Vol_MA20")
macd_col  = col(df, "MACD(元)",        "MACD")
macd_sig  = col(df, "MACD_Signal(元)", "MACD_Signal")
macd_hist = col(df, "MACD_Hist(元)",   "MACD_Hist")
kd_k      = col(df, "K值(%)", "K值")
kd_d      = col(df, "D值(%)", "D值")
fi_col    = col(df, "外資買賣超(張)",   "外資買賣超")
it_col    = col(df, "投信買賣超(張)",   "投信買賣超")
dl_col    = col(df, "自營商買賣超(張)", "自營商買賣超")
mb_col    = col(df, "融資餘額(張)", "融資餘額")
ss_col    = col(df, "融券餘額(張)", "融券餘額")

# 面板設定：(名稱, secondary_y, 高度比例)
_PANEL_CFG = [
    ("K線",   False, 0.40),
    ("成交量", False, 0.13),
    ("MACD",  False, 0.15),
    ("KD/RSI", True, 0.15),
    ("法人",  False, 0.10),
    ("融資券",  True, 0.07),
]
_active_cfg = [(p, sy, h) for p, sy, h in _PANEL_CFG if p in active_panels]

if not _active_cfg:
    st.info("請在側邊欄勾選至少一個面板")
else:
    _n       = len(_active_cfg)
    _h_sum   = sum(h for _, _, h in _active_cfg)
    _heights = [h / _h_sum for _, _, h in _active_cfg]
    _specs   = [[{"secondary_y": sy}] for _, sy, _ in _active_cfg]
    _row_map = {p: i + 1 for i, (p, _, _h) in enumerate(_active_cfg)}

    fig_main = make_subplots(
        rows=_n, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=_heights,
        specs=_specs,
    )

    # ── K線 ──
    if "K線" in _row_map:
        _r = _row_map["K線"]
        fig_main.add_trace(go.Candlestick(
            x=df_show.index, open=df_show[o_col], high=df_show[h_col],
            low=df_show[l_col], close=df_show[close_col],
            name="K線", increasing_line_color="#ef5350", decreasing_line_color="#26a69a",
        ), row=_r, col=1)
        if bbu:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[bbl], name="BB帶",
                line=dict(color="rgba(255,165,0,0.4)", dash="dot"),
                legendgroup="BB", showlegend=True, fill=None), row=_r, col=1)
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[bbu], name="BB上軌",
                line=dict(color="rgba(255,165,0,0.4)", dash="dot"),
                legendgroup="BB", showlegend=False,
                fill="tonexty", fillcolor="rgba(255,165,0,0.07)"), row=_r, col=1)
        if bbm:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[bbm], name="BB中軌",
                line=dict(color="rgba(255,165,0,0.9)", dash="dash"),
                legendgroup="BB", showlegend=False), row=_r, col=1)
        for ma_c, clr, lbl in [(ma5, "#ff9800", "MA5"), (ma20, "#2196F3", "MA20"), (ma60, "#9C27B0", "MA60")]:
            if ma_c:
                fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[ma_c], name=lbl,
                    line=dict(color=clr, width=1.2)), row=_r, col=1)
        if _sig_col and h_col and l_col:
            bull_x, bull_y, bull_txt = [], [], []
            bear_x, bear_y, bear_txt = [], [], []
            for date_idx, drow in df_show.iterrows():
                sig_str = str(drow.get(_sig_col, ""))
                for kw, _lc, anno in _VLINE_SIGNALS:
                    if kw in sig_str:
                        if "買" in anno or "金叉" in anno:
                            bull_x.append(date_idx); bull_y.append(drow[l_col] * 0.997)
                            bull_txt.append(anno.replace("▲ ", ""))
                        else:
                            bear_x.append(date_idx); bear_y.append(drow[h_col] * 1.003)
                            bear_txt.append(anno.replace("▼ ", ""))
                        break
            if bull_x:
                fig_main.add_trace(go.Scatter(
                    x=bull_x, y=bull_y, mode="markers+text",
                    marker=dict(symbol="triangle-up", size=10, color="#ef5350"),
                    text=bull_txt, textposition="bottom center",
                    textfont=dict(size=9, color="#ef5350"), name="買訊",
                ), row=_r, col=1)
            if bear_x:
                fig_main.add_trace(go.Scatter(
                    x=bear_x, y=bear_y, mode="markers+text",
                    marker=dict(symbol="triangle-down", size=10, color="#26a69a"),
                    text=bear_txt, textposition="top center",
                    textfont=dict(size=9, color="#26a69a"), name="賣訊",
                ), row=_r, col=1)
        _gap = find_latest_active_gap(df, h_col, l_col) if (h_col and l_col) else None
        if _gap:
            _gtype, _gy0, _gy1, _glabel = _gap
            fig_main.add_hrect(
                y0=_gy0, y1=_gy1, row=_r, col=1,
                fillcolor="rgba(239,83,80,0.18)" if _gtype == "up" else "rgba(38,166,154,0.18)",
                line_width=0,
                annotation_text=_glabel, annotation_position="left",
                annotation_font_size=10,
                annotation_font_color="#ef5350" if _gtype == "up" else "#26a69a",
            )
        fig_main.update_yaxes(title_text="價格(元)", row=_r, col=1, title_standoff=4)

    # ── 成交量 ──
    if "成交量" in _row_map and vol_col:
        _r = _row_map["成交量"]
        vol_colors = ["#ef5350" if df_show[close_col].iloc[i] >= df_show[close_col].iloc[i-1]
                      else "#26a69a" for i in range(len(df_show))]
        fig_main.add_trace(go.Bar(x=df_show.index, y=df_show[vol_col], name="成交量",
            marker_color=vol_colors, opacity=0.7), row=_r, col=1)
        if vma5_col:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[vma5_col], name="Vol MA5",
                line=dict(color="#ff9800", width=1.2)), row=_r, col=1)
        if vma20_col:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[vma20_col], name="Vol MA20",
                line=dict(color="#2196F3", width=1.2)), row=_r, col=1)
        fig_main.update_yaxes(title_text="量(張)", row=_r, col=1, title_standoff=4)

    # ── MACD ──
    if "MACD" in _row_map and macd_col:
        _r = _row_map["MACD"]
        if macd_hist:
            hc = ["#ef5350" if v >= 0 else "#26a69a" for v in df_show[macd_hist].fillna(0)]
            fig_main.add_trace(go.Bar(x=df_show.index, y=df_show[macd_hist], name="MACD Hist",
                marker_color=hc, opacity=0.6), row=_r, col=1)
        fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[macd_col], name="MACD",
            line=dict(color="#2196F3", width=1.5)), row=_r, col=1)
        if macd_sig:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[macd_sig], name="DIF",
                line=dict(color="#ff9800", width=1.5)), row=_r, col=1)
        fig_main.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5, row=_r, col=1)
        fig_main.update_yaxes(title_text="MACD", row=_r, col=1, title_standoff=4)

    # ── KD/RSI ──
    if "KD/RSI" in _row_map:
        _r = _row_map["KD/RSI"]
        if kd_k:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[kd_k], name="K",
                line=dict(color="#2196F3")), row=_r, col=1)
        if kd_d:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[kd_d], name="D",
                line=dict(color="#ff9800")), row=_r, col=1)
        if rsi_col:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[rsi_col], name="RSI14",
                line=dict(color="#9C27B0", dash="dot")), row=_r, col=1, secondary_y=True)
            fig_main.update_yaxes(title_text="RSI(%)", secondary_y=True, row=_r, col=1, title_standoff=4)
        fig_main.add_hline(y=80, line_dash="dash", line_color="rgba(239,83,80,0.35)",  row=_r, col=1)
        fig_main.add_hline(y=20, line_dash="dash", line_color="rgba(38,166,154,0.35)", row=_r, col=1)
        if rsi_col:
            fig_main.add_hline(y=70, line_dash="dot",  line_color="rgba(239,83,80,0.25)",  row=_r, col=1, secondary_y=True)
            fig_main.add_hline(y=30, line_dash="dot",  line_color="rgba(38,166,154,0.25)", row=_r, col=1, secondary_y=True)
        fig_main.update_yaxes(title_text="KD(%)", row=_r, col=1, title_standoff=4)

    # ── 法人 ──
    if "法人" in _row_map and (fi_col or it_col or dl_col):
        _r = _row_map["法人"]
        if fi_col:
            fig_main.add_trace(go.Bar(x=df_show.index, y=df_show[fi_col], name="外資",
                marker_color="#2196F3", opacity=0.8), row=_r, col=1)
        if it_col:
            fig_main.add_trace(go.Bar(x=df_show.index, y=df_show[it_col], name="投信",
                marker_color="#ff9800", opacity=0.8), row=_r, col=1)
        if dl_col:
            fig_main.add_trace(go.Bar(x=df_show.index, y=df_show[dl_col], name="自營",
                marker_color="#9C27B0", opacity=0.8), row=_r, col=1)
        fig_main.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4, row=_r, col=1)
        fig_main.update_yaxes(title_text="法人(張)", row=_r, col=1, title_standoff=4)

    # ── 融資券 ──
    if "融資券" in _row_map and (mb_col or ss_col):
        _r = _row_map["融資券"]
        if mb_col:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[mb_col], name="融資餘額",
                line=dict(color="#ef5350", width=1.8)), row=_r, col=1)
        if ss_col:
            fig_main.add_trace(go.Scatter(x=df_show.index, y=df_show[ss_col], name="融券餘額",
                line=dict(color="#26a69a", width=1.8)), row=_r, col=1, secondary_y=True)
            fig_main.update_yaxes(title_text="融券(張)", secondary_y=True, row=_r, col=1, title_standoff=4)
        if mb_col:
            fig_main.update_yaxes(title_text="融資(張)", row=_r, col=1, title_standoff=4)

    for _ri in range(1, _n):
        fig_main.update_xaxes(showticklabels=False, row=_ri, col=1)
    fig_main.update_layout(
        height=max(300, int(1060 * _n / 6)),
        xaxis_rangeslider_visible=False,
        margin=dict(t=20, b=20, l=60, r=60),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0,
                    font=dict(size=11)),
        hovermode="x unified",
        barmode="relative",
    )
    st.plotly_chart(fig_main, use_container_width=True)

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
