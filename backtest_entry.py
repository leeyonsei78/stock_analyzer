"""진입 시점 백테스트: 신호 발생 다음 날 시가 매수 vs 종가 매수 (+ 신호일 종가 매수).

신호는 analyzer.score()의 6개 체크를 일자별로 벡터화한 것(신호일 종가까지의 정보만 사용).
  A) 다음 날 시가 매수   B) 다음 날 종가 매수   C) 신호일 종가 매수
세 방식 모두 신호일+1+h 일의 종가에 청산해 청산일을 같게 맞춘다.

사용: python backtest_entry.py [--years 3] [--hold 1 3 5] [--cost 0.25]
"""
import argparse

import numpy as np
import pandas as pd

from analyzer import add_indicators

# 유동성 큰 코스피 종목 (상장목록 조회 의존성을 피하려고 고정)
UNIVERSE = [
    "005930", "000660", "035420", "051910", "005380", "207940", "105560", "005490",
    "012450", "035720", "009540", "034020", "017670", "010950", "090430", "352820",
    "000270", "055550", "086790", "032830", "068270", "028260", "066570", "003550",
    "096770", "015760", "033780", "011200", "030200", "018260",
]


def signals(df: pd.DataFrame) -> pd.DataFrame:
    """analyzer.score()의 6개 체크를 일자별 boolean 컬럼으로."""
    c = df["Close"]
    high20 = c.shift(1).rolling(20).max()
    out = pd.DataFrame(index=df.index)
    out["거래량급증"] = df.VOL_ratio >= 2
    out["20일신고가"] = c > high20
    out["정배열"] = (df.MA5 > df.MA20) & (df.MA20 > df.MA60)
    out["MACD골든"] = (df.MACD.shift(1) <= df.MACD_signal.shift(1)) & (df.MACD > df.MACD_signal)
    out["RSI50~70"] = df.RSI.between(50, 70)
    out["볼린저상단"] = c >= df.BB_upper * 0.98
    out["점수"] = out.sum(axis=1)
    return out


def trades(df: pd.DataFrame, hold: int) -> pd.DataFrame:
    """신호일 t 기준 세 가지 진입의 수익률(%). 청산은 모두 t+1+hold 종가."""
    o, c = df["Open"], df["Close"]
    exit_px = c.shift(-(1 + hold))
    t = pd.DataFrame(index=df.index)
    t["A_다음날시가"] = (exit_px / o.shift(-1) - 1) * 100
    t["B_다음날종가"] = (exit_px / c.shift(-1) - 1) * 100
    t["C_신호일종가"] = (exit_px / c - 1) * 100
    t["gap"] = (o.shift(-1) / c - 1) * 100  # 신호일 종가 → 다음 날 시가 갭
    return t


def run(prices: dict[str, pd.DataFrame], holds=(1, 3, 5), cost=0.25, min_score=4) -> dict:
    frames = {h: [] for h in holds}
    for sym, raw in prices.items():
        df = raw[raw["Volume"] > 0].dropna(subset=["Open", "Close"])
        if len(df) < 150:
            continue
        df = add_indicators(df)
        sig = signals(df)
        for h in holds:
            t = trades(df, h)
            f = pd.concat([sig, t], axis=1)
            f["symbol"] = sym
            frames[h].append(f.dropna())
    return {h: pd.concat(v) for h, v in frames.items() if v}


def summarize(data: dict, cost: float, min_score: int) -> str:
    cols = ["A_다음날시가", "B_다음날종가", "C_신호일종가"]
    lines = []
    for h, f in data.items():
        lines.append(f"\n=== 보유: 진입 후 {h}일 (청산=신호일+{1 + h}일 종가), 왕복비용 {cost}% 차감 ===")
        groups = {
            "전체(기준선)": f,
            f"점수>={min_score}": f[f["점수"] >= min_score],
            "거래량급증": f[f["거래량급증"]],
            "20일신고가": f[f["20일신고가"]],
            "MACD골든": f[f["MACD골든"]],
        }
        lines.append(f"{'그룹':<12}{'표본':>8}" + "".join(f"{c:>26}" for c in cols))
        lines.append(f"{'':<20}" + "".join(f"{'평균%/승률%/t':>26}" for _ in cols))
        for name, g in groups.items():
            if len(g) < 30:
                lines.append(f"{name:<12}{len(g):>8}  (표본 30 미만, 생략)")
                continue
            row = f"{name:<12}{len(g):>8}"
            for c in cols:
                r = g[c] - cost
                t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if r.std() > 0 else float("nan")
                row += f"{r.mean():>10.2f}/{(r > 0).mean() * 100:>5.1f}/{t:>6.2f}   "
            lines.append(row)
        g = f[f["점수"] >= min_score]
        if len(g) >= 30:
            lines.append(f"  점수>={min_score} 평균 갭(신호일종가→다음날시가): {g['gap'].mean():.2f}%  (전체 {f['gap'].mean():.2f}%)")
    lines.append(
        "\n주의: 같은 종목의 인접 신호일은 보유기간이 겹쳐 독립이 아니므로 t값은 과대평가된다. "
        "표본 구간의 시장 방향(상승장/하락장)에 크게 좌우되니 '기준선' 대비 차이로 볼 것."
    )
    return "\n".join(lines)


def main():
    import FinanceDataReader as fdr

    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--hold", type=int, nargs="+", default=[1, 3, 5])
    ap.add_argument("--cost", type=float, default=0.25, help="왕복 거래비용 %% (수수료+거래세 추정)")
    ap.add_argument("--min-score", type=int, default=4)
    a = ap.parse_args()

    start = (pd.Timestamp.today() - pd.Timedelta(days=365 * a.years)).strftime("%Y-%m-%d")
    prices = {}
    for s in UNIVERSE:
        try:
            prices[s] = fdr.DataReader(s, start)
        except Exception as e:
            print(f"[skip] {s}: {e}")
    print(f"종목 {len(prices)}개 로드, 기간 {start} ~")
    data = run(prices, tuple(a.hold), a.cost, a.min_score)
    print(summarize(data, a.cost, a.min_score))


if __name__ == "__main__":
    main()
