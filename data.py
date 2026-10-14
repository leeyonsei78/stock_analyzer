"""데이터 수집: KRX 종목/시세(FinanceDataReader), 네이버 증권 모바일 API, DART 공시."""
import html
import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, timedelta
from functools import lru_cache

import FinanceDataReader as fdr
import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
NAVER = "https://m.stock.naver.com/api"


def num(s) -> float | None:
    if s is None:
        return None
    s = re.sub(r"[^\d.\-]", "", str(s))
    try:
        return float(s)
    except ValueError:
        return None


def _get(url: str, **params):
    r = requests.get(url, headers=HEADERS, params=params, timeout=10)
    r.raise_for_status()
    return r


@lru_cache(maxsize=1)
def listing() -> pd.DataFrame:
    """KRX 전 종목 (시총·거래대금 포함) + 업종/주요제품."""
    base = fdr.StockListing("KRX")
    desc = fdr.StockListing("KRX-DESC")[["Code", "Industry", "Products"]]
    df = base.merge(desc, on="Code", how="left")
    df["Industry"] = df["Industry"].fillna("기타(미분류)")
    return df


def find_stock(query: str) -> pd.Series | None:
    q = query.strip()
    if not q:
        return None
    df = listing()
    key = q.replace(" ", "").lower()
    names = df["Name"].str.replace(" ", "").str.lower()
    for mask in (df["Code"] == q, names == key, names.str.contains(re.escape(key), na=False)):
        hit = df[mask]
        if not hit.empty:
            return hit.sort_values("Marcap", ascending=False).iloc[0]
    return None


def history(code: str, days: int = 400) -> pd.DataFrame:
    start = (date.today() - timedelta(days=days)).isoformat()
    return fdr.DataReader(code, start)


# ---- 네이버 증권 ----------------------------------------------------------
def naver_trend(code: str, n: int = 20) -> list[dict]:
    """일별 외국인/기관/개인 순매수량. 최신일 먼저."""
    rows = _get(f"{NAVER}/stock/{code}/trend", pageSize=n).json()
    return [
        {
            "date": r["bizdate"],
            "foreign": num(r["foreignerPureBuyQuant"]),
            "organ": num(r["organPureBuyQuant"]),
            "individual": num(r["individualPureBuyQuant"]),
            "foreign_ratio": num(r["foreignerHoldRatio"]),
            "close": num(r["closePrice"]),
        }
        for r in rows
    ]


def naver_news(code: str, n: int = 8) -> list[str]:
    try:
        data = _get(f"{NAVER}/news/stock/{code}", pageSize=n, page=1).json()
    except Exception:
        return []
    titles = []
    for cluster in data:
        for item in cluster.get("items", [])[:1]:
            titles.append(html.unescape(item.get("titleFull") or item.get("title", "")))
    return [t for t in titles if t][:n]


def naver_info(code: str) -> dict:
    data = _get(f"{NAVER}/stock/{code}/integration").json()
    return {i["code"]: i["value"] for i in data.get("totalInfos", [])}


def naver_finance(code: str) -> dict:
    """연간 재무: 가장 최근 확정(비컨센서스) 연도 값."""
    data = _get(f"{NAVER}/stock/{code}/finance/annual").json()["financeInfo"]
    keys = [t["key"] for t in data["trTitleList"] if t["isConsensus"] == "N"]
    if not keys:
        return {}
    latest, prior = keys[-1], keys[-2] if len(keys) > 1 else None
    out = {"period": latest}
    for row in data["rowList"]:
        cols = row["columns"]
        out[row["title"]] = num(cols.get(latest, {}).get("value"))
        if prior:
            out[row["title"] + "_prev"] = num(cols.get(prior, {}).get("value"))
    return out


# ---- DART (선택: DART_API_KEY) -------------------------------------------
@lru_cache(maxsize=1)
def _dart_codes(key: str) -> dict[str, str]:
    r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml", params={"crtfc_key": key}, timeout=30)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    return {
        e.findtext("stock_code").strip(): e.findtext("corp_code")
        for e in root.iter("list")
        if (e.findtext("stock_code") or "").strip()
    }


def dart_disclosures(code: str, months: int = 3) -> list[str] | None:
    """최근 공시 제목 목록. 키가 없거나 실패하면 None(확인 불가)."""
    key = os.getenv("DART_API_KEY")
    if not key:
        return None
    try:
        corp = _dart_codes(key).get(code)
        if not corp:
            return None
        bgn = (date.today() - timedelta(days=30 * months)).strftime("%Y%m%d")
        j = requests.get(
            "https://opendart.fss.or.kr/api/list.json",
            params={"crtfc_key": key, "corp_code": corp, "bgn_de": bgn, "page_count": 30},
            timeout=15,
        ).json()
        return [f"{i['rcept_dt']} {i['report_nm']}" for i in j.get("list", [])]
    except Exception:
        return None
