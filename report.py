"""STEP 2: 종목 분석 리포트 (기본정보 → 공시/재료 → 테마 → 수급 → 차트 → 리스크 → 최종판단)."""
from datetime import date

import pandas as pd

import analyzer
import data
import llm


def _eok(v):  # 네이버 재무 단위는 억원
    return None if v is None else f"{v:,.0f}억원"


def gather(code: str, name: str, market: str, industry: str) -> dict:
    """리포트에 필요한 사실 데이터를 모은다. 개별 소스 실패는 None으로 둔다."""
    facts: dict = {"code": code, "name": name, "market": market, "industry": industry, "date": date.today().isoformat()}

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception:
            return None

    facts["info"] = safe(data.naver_info, code) or {}
    facts["finance"] = safe(data.naver_finance, code) or {}
    facts["news"] = data.naver_news(code, 8)
    facts["disclosures"] = data.dart_disclosures(code)  # None = 확인 불가
    trend = safe(data.naver_trend, code, 20) or []
    facts["flow"] = {
        "days": len(trend),
        "foreign": sum(t["foreign"] or 0 for t in trend),
        "organ": sum(t["organ"] or 0 for t in trend),
        "individual": sum(t["individual"] or 0 for t in trend),
        "foreign_ratio_now": trend[0]["foreign_ratio"] if trend else None,
        "foreign_ratio_old": trend[-1]["foreign_ratio"] if trend else None,
    }

    df = safe(lambda: analyzer.add_indicators(data.history(code, 400)))
    if df is not None and len(df) > 60:
        last = df.iloc[-1]
        hi52, lo52 = df["High"].iloc[-250:].max(), df["Low"].iloc[-250:].min()
        recent = df.iloc[-16:]
        box = (recent["High"].max() - recent["Low"].min()) / recent["Low"].min() * 100
        facts["chart"] = {
            "price": float(last.Close), "hi52": float(hi52), "lo52": float(lo52),
            "from_hi_pct": float(last.Close / hi52 * 100),
            "volx": float(last.VOL_ratio),
            "aligned": bool(last.MA5 > last.MA20 > last.MA60 > last.MA120),
            "reverse": bool(last.MA5 < last.MA20 < last.MA60),
            "above_ma60": bool(last.Close > last.MA60),
            "trend60": float(last.Close / df["Close"].iloc[-61] * 100 - 100),
            "ret5": float(last.Close / df["Close"].iloc[-6] * 100 - 100),
            "rsi": float(last.RSI),
            "box_width_pct": float(box),
            "ma60": float(last.MA60),
        }
    return facts


def _rule_based(f: dict) -> dict:
    """LLM이 없을 때의 규칙 기반 해석/판단."""
    ch, fl, fin = f.get("chart") or {}, f["flow"], f["finance"]
    score, why = 0, []
    if fl["organ"] > 0:
        score += 1; why.append("기관 20일 순매수")
    if fl["foreign"] > 0:
        score += 1; why.append("외국인 20일 순매수")
    if ch.get("above_ma60"):
        score += 1; why.append("60일선 위")
    if ch.get("aligned"):
        score += 1; why.append("이평선 정배열")
    if ch.get("volx", 0) >= 2:
        score += 1; why.append("거래량 급증")
    if ch.get("rsi", 50) > 75:
        score -= 1; why.append("RSI 과열")
    debt = fin.get("부채비율")
    risk = []
    if debt and debt > 200:
        risk.append(f"부채비율 {debt:.0f}%로 높음")
    if ch.get("reverse"):
        risk.append("이평선 역배열(하락 추세)")
    if ch.get("from_hi_pct", 100) > 95:
        risk.append("52주 고점 부근 (추격 부담)")
    if not risk:
        risk.append("뚜렷한 구조적 리스크는 데이터상 확인되지 않음")

    short = "즉시매수" if score >= 4 else "분할매수" if score >= 3 else "관망" if score >= 1 else "패스"
    mid_ok = (fin.get("영업이익") or 0) > 0 and (not debt or debt < 200) and not ch.get("reverse")
    return {
        "basic": f"{f['name']}({f['code']}, {f['market']}), 업종 {f['industry']}.",
        "material": "최근 뉴스/공시를 아래 목록에서 직접 확인하세요." if f["news"] else "수집된 뉴스가 없습니다.",
        "theme": f"업종: {f['industry']}.",
        "flow": f"최근 {fl['days']}거래일 외국인 {fl['foreign']:+,.0f}주, 기관 {fl['organ']:+,.0f}주 순매수.",
        "chart": "정배열" if ch.get("aligned") else "역배열" if ch.get("reverse") else "혼조",
        "risks": risk,
        "short": {"verdict": short, "reasons": why or ["뚜렷한 긍정 신호 없음"],
                  "scenario": "추가 매수는 60일선 돌파·안착 확인 후" if short in ("분할매수", "관망") else ""},
        "mid": {"verdict": "분할매수" if mid_ok and score >= 3 else "관망" if mid_ok else "패스",
                "reasons": ["영업이익 흑자·부채비율 양호" if mid_ok else "재무/추세 조건 미충족"],
                "scenario": ""},
        "conclusion": "규칙 기반 판단입니다. ANTHROPIC_API_KEY를 설정하면 AI가 뉴스·재무를 종합해 서술합니다.",
        "engine": "rules",
    }


def analyze(facts: dict) -> dict:
    ai = llm.ask_json(
        "당신은 한국 주식 애널리스트입니다. 아래 사실 데이터만 근거로 분석하세요. 데이터에 없는 사실(공시, 수치)은 "
        "만들지 말고 '확인 불가'라고 쓰세요. 매수 권유가 아니라 참고용 판단입니다. verdict는 반드시 "
        "'즉시매수|분할매수|관망|패스' 중 하나. 스키마: "
        '{"basic":str,"material":str,"theme":str,"flow":str,"chart":str,"risks":[str],'
        '"short":{"verdict":str,"reasons":[str],"scenario":str},'
        '"mid":{"verdict":str,"reasons":[str],"scenario":str},"conclusion":str}',
        f"사실 데이터:\n{facts}",
    )
    base = _rule_based(facts)
    if ai and "short" in ai and "mid" in ai:
        base.update(ai)
        base["engine"] = llm.provider()
    return {"facts": facts, "analysis": base}
