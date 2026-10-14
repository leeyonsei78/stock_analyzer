"""종목 분석 로직: 지표 계산 + 급등 신호 점수화."""
import pandas as pd
import FinanceDataReader as fdr


def load_prices(symbol: str, days: int = 400) -> pd.DataFrame:
    start = (pd.Timestamp.today() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    df = fdr.DataReader(symbol, start)
    if df.empty:
        raise ValueError(f"'{symbol}' 데이터를 찾을 수 없습니다.")
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    for n in (5, 20, 60, 120):
        df[f"MA{n}"] = c.rolling(n).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    mid = df["MA20"]
    std = c.rolling(20).std()
    df["BB_upper"] = mid + 2 * std
    df["BB_lower"] = mid - 2 * std

    df["VOL_MA20"] = df["Volume"].rolling(20).mean()
    df["VOL_ratio"] = df["Volume"] / df["VOL_MA20"]
    return df


def score(df: pd.DataFrame) -> tuple[int, list[tuple[str, bool, str]]]:
    """마지막 거래일 기준 급등 신호 체크리스트. (점수, [(항목, 충족, 설명)])"""
    last, prev = df.iloc[-1], df.iloc[-2]
    high20 = df["Close"].iloc[-21:-1].max()
    checks = [
        ("거래량 급증", last.VOL_ratio >= 2, f"20일 평균 대비 {last.VOL_ratio:.1f}배"),
        ("20일 신고가 돌파", last.Close > high20, f"종가 {last.Close:,.0f} / 직전 20일 고가 {high20:,.0f}"),
        ("정배열 (5>20>60)", last.MA5 > last.MA20 > last.MA60, "단기>중기>장기 이동평균"),
        ("MACD 골든크로스", prev.MACD <= prev.MACD_signal and last.MACD > last.MACD_signal, "MACD가 시그널선 상향 돌파"),
        ("RSI 50~70 (상승 추세, 과열 아님)", 50 <= last.RSI <= 70, f"RSI {last.RSI:.1f}"),
        ("볼린저 상단 근접/돌파", last.Close >= last.BB_upper * 0.98, "변동성 확대 구간"),
    ]
    return sum(ok for _, ok, _ in checks), checks


def verdict(points: int, total: int) -> str:
    r = points / total
    if r >= 0.67:
        return "강한 상승 신호"
    if r >= 0.34:
        return "관망 / 일부 신호"
    return "신호 약함"
