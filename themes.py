"""후보 종목을 테마로 묶고 거시 트리거 / 대장주 / 수혜주를 붙인다."""
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import data
import llm


def _peers(row: pd.Series, exclude: set[str], k: int = 6) -> list[dict]:
    lst = data.listing()
    p = lst[(lst["Industry"] == row["Industry"]) & (~lst["Code"].isin(exclude))]
    p = p.sort_values("Marcap", ascending=False).head(k)
    return [{"code": r.Code, "name": r.Name, "market": r.Market} for r in p.itertuples()]


def _stock(row: pd.Series, role: str, reason: str) -> dict:
    return {
        "code": row["Code"], "name": row["Name"], "market": row["Market"],
        "ret5": round(row["ret5"], 1), "volx": round(row["volx"], 1),
        "new_high": bool(row["new_high"]), "role": role, "reason": reason,
    }


def _fallback(cands: pd.DataFrame, news: dict[str, list[str]]) -> list[dict]:
    """LLM 없이 업종(Industry)별로 묶는다. 5일 상승률이 가장 큰 종목을 대장주로."""
    themes = []
    for ind, g in cands.groupby("Industry"):
        g = g.sort_values("ret5", ascending=False)
        lead = g.iloc[0]
        heads = news.get(lead["Code"], [])
        themes.append({
            "name": ind,
            "trigger": heads[0] if heads else "뉴스 트리거 확인 불가 (ANTHROPIC_API_KEY 설정 시 AI가 테마를 요약합니다)",
            "stocks": [_stock(r, "대장주" if i == 0 else "관련주", "") for i, (_, r) in enumerate(g.iterrows())],
            "beneficiaries": [
                {**p, "reason": "동일 업종 시총 상위"} for p in _peers(lead, set(cands["Code"]))
            ][:3],
            "ret5": round(g["ret5"].mean(), 1),
        })
    return sorted(themes, key=lambda t: (-len(t["stocks"]), -t["ret5"]))


def build_themes(cands: pd.DataFrame, max_candidates: int = 30) -> list[dict]:
    if cands.empty:
        return []
    cands = cands.head(max_candidates)
    with ThreadPoolExecutor(8) as ex:
        news = dict(zip(cands["Code"], ex.map(lambda c: data.naver_news(c, 4), cands["Code"])))

    if not llm.available():
        return _fallback(cands, news)

    by_code = cands.set_index("Code", drop=False)
    exclude = set(cands["Code"])
    payload = [
        {
            "code": r.Code, "name": r.Name, "industry": r.Industry, "products": str(r.Products)[:60],
            "ret5_pct": round(r.ret5, 1), "vol_x": round(r.volx, 1), "news": news.get(r.Code, []),
            "peers": _peers(pd.Series(r._asdict()), exclude, 5),
        }
        for r in cands.itertuples()
    ]
    res = llm.ask_json(
        "당신은 한국 주식 수급 테마 분석가입니다. 급등 후보를 같은 재료/테마끼리 묶으세요. "
        "각 테마마다 거시 트리거(왜 돈이 몰렸는지 1~2문장, 뉴스 근거), 대장주, "
        "수혜주(반드시 각 종목의 peers 목록에 있는 코드만)를 고르세요. 모르면 '미분류' 테마로 두세요. "
        '스키마: {"themes":[{"name":str,"trigger":str,"stocks":[{"code":str,"role":"대장주|직접수혜|관련주","reason":str}],'
        '"beneficiaries":[{"code":str,"reason":str}]}]}',
        f"후보 종목 데이터:\n{payload}",
    )
    if not res or "themes" not in res:
        return _fallback(cands, news)

    peer_names = {p["code"]: p for item in payload for p in item["peers"]}
    out = []
    for t in res["themes"]:
        stocks = [_stock(by_code.loc[s["code"]], s.get("role", "관련주"), s.get("reason", ""))
                  for s in t.get("stocks", []) if s.get("code") in by_code.index]
        if not stocks:
            continue
        bens = [{**peer_names[b["code"]], "reason": b.get("reason", "")}
                for b in t.get("beneficiaries", []) if b.get("code") in peer_names]
        out.append({
            "name": t.get("name", "미분류"), "trigger": t.get("trigger", ""),
            "stocks": stocks, "beneficiaries": bens,
            "ret5": round(sum(s["ret5"] for s in stocks) / len(stocks), 1),
        })
    return sorted(out, key=lambda t: (-len(t["stocks"]), -t["ret5"])) or _fallback(cands, news)
