"""STEP 1: 수급 후보 스캔 (5일 누적 상승률 / 거래량 배수 / 상승일 수 / 시총)."""
import pickle
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

import data

CACHE_DIR = Path(__file__).parent / ".cache"


def _metrics(code: str) -> dict | None:
    try:
        df = data.history(code, days=120)
        if len(df) < 25:
            return None
        c, v = df["Close"], df["Volume"]
        last5 = c.iloc[-6:]
        return {
            "Code": code,
            "ret5": (c.iloc[-1] / c.iloc[-6] - 1) * 100,
            "volx": v.iloc[-1] / max(v.iloc[-21:-1].mean(), 1),
            "up_days": int((last5.diff().dropna() > 0).sum()),
            "new_high": bool(c.iloc[-1] >= df["High"].iloc[-60:].max()),
            "last_chg": (c.iloc[-1] / c.iloc[-2] - 1) * 100,
        }
    except Exception:
        return None


def scan(
    min_ret5: float = 15,
    min_volx: float = 2.0,
    min_up_days: int = 3,
    min_marcap_eok: float = 1000,
    n_stocks: int = 1200,
    force: bool = False,
    progress: Callable[[float, str], None] | None = None,
) -> pd.DataFrame:
    """조건을 모두 만족하는 후보 DataFrame (ret5 내림차순)."""
    lst = data.listing()
    lst = lst[lst["Marcap"] >= min_marcap_eok * 1e8]
    lst = lst.sort_values("Amount", ascending=False).head(n_stocks)
    codes = lst["Code"].tolist()

    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"metrics_{date.today():%Y%m%d}.pkl"
    cache: dict = {}
    if cache_file.exists() and not force:
        cache = pickle.loads(cache_file.read_bytes())

    todo = [c for c in codes if c not in cache]
    if todo:
        with ThreadPoolExecutor(16) as ex:
            for i, m in enumerate(ex.map(_metrics, todo), 1):
                if m:
                    cache[m["Code"]] = m
                if progress and i % 20 == 0:
                    progress(0.8 * i / len(todo), f"시세 수급 스캔 중... ({i}/{len(todo)})")
        cache_file.write_bytes(pickle.dumps(cache))

    m = pd.DataFrame([cache[c] for c in codes if c in cache])
    if m.empty:
        return m
    out = m.merge(lst[["Code", "Name", "Market", "Marcap", "Industry", "Products", "Close"]], on="Code")
    out = out[(out.ret5 >= min_ret5) & (out.volx >= min_volx) & (out.up_days >= min_up_days)]
    return out.sort_values("ret5", ascending=False).reset_index(drop=True)
