import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import FinanceDataReader as fdr
from analyzer import add_indicators, load_prices, score, verdict

st.set_page_config(page_title="종목 분석기", layout="wide")
st.title("📈 종목 분석기 - 급등 신호 체크")


@st.cache_data(ttl=3600)
def listing() -> pd.DataFrame:
    return fdr.StockListing("KRX")[["Code", "Name", "Market"]]


@st.cache_data(ttl=600)
def prices(symbol: str) -> pd.DataFrame:
    return add_indicators(load_prices(symbol))


query = st.text_input("종목명 또는 코드 (예: 삼성전자, 005930, AAPL)", "삼성전자")

symbol, name = query.strip(), query.strip()
if query.strip():
    lst = listing()
    hit = lst[(lst.Name == query.strip()) | (lst.Code == query.strip())]
    if hit.empty:
        hit = lst[lst.Name.str.contains(query.strip(), na=False)]
    if not hit.empty:
        symbol, name = hit.iloc[0].Code, hit.iloc[0].Name

try:
    df = prices(symbol)
except Exception as e:
    st.error(f"데이터를 불러오지 못했습니다: {e}")
    st.stop()

pts, checks = score(df)
last, prev = df.iloc[-1], df.iloc[-2]
chg = (last.Close / prev.Close - 1) * 100

c1, c2, c3 = st.columns(3)
c1.metric(f"{name} ({symbol})", f"{last.Close:,.0f}", f"{chg:+.2f}%")
c2.metric("신호 점수", f"{pts} / {len(checks)}")
c3.metric("종합", verdict(pts, len(checks)))

view = df.iloc[-180:]
fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2], vertical_spacing=0.03)
fig.add_trace(go.Candlestick(x=view.index, open=view.Open, high=view.High, low=view.Low, close=view.Close, name="주가"), 1, 1)
for col in ("MA5", "MA20", "MA60", "MA120"):
    fig.add_trace(go.Scatter(x=view.index, y=view[col], name=col, line=dict(width=1)), 1, 1)
fig.add_trace(go.Bar(x=view.index, y=view.Volume, name="거래량"), 2, 1)
fig.add_trace(go.Scatter(x=view.index, y=view.RSI, name="RSI"), 3, 1)
fig.add_hline(y=70, line_dash="dot", row=3, col=1)
fig.add_hline(y=30, line_dash="dot", row=3, col=1)
fig.update_layout(height=750, xaxis_rangeslider_visible=False, margin=dict(t=20))
st.plotly_chart(fig, use_container_width=True)

st.subheader("신호 체크리스트")
for label, ok, desc in checks:
    st.write(f"{'✅' if ok else '⬜'} **{label}** — {desc}")

st.caption("참고용 정보이며 투자 판단과 손익의 책임은 본인에게 있습니다.")
