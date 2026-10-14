"""웹 서버: FastAPI. 실행: python server.py  ->  http://127.0.0.1:8000"""
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import data
import llm
import report
import scanner
import themes

app = FastAPI(title="종목 검색기")
STATIC = Path(__file__).parent / "static"
jobs: dict[str, dict] = {}


class ScanParams(BaseModel):
    min_ret5: float = 15
    min_volx: float = 2.0
    min_up_days: int = 3
    min_marcap_eok: float = 1000
    n_stocks: int = 1200
    force: bool = False


class AnalyzeParams(BaseModel):
    query: str


def _run_scan(job_id: str, p: ScanParams) -> None:
    job = jobs[job_id]
    try:
        def prog(frac: float, msg: str) -> None:
            job.update(progress=frac, message=msg)

        cands = scanner.scan(p.min_ret5, p.min_volx, p.min_up_days, p.min_marcap_eok, p.n_stocks, p.force, prog)
        prog(0.85, "테마 그룹핑 중...")
        result = themes.build_themes(cands) if len(cands) else []
        job.update(status="done", progress=1.0, message="완료", candidates=len(cands), themes=result,
                   llm_error=llm.last_error)
    except Exception as e:
        job.update(status="error", message=f"{type(e).__name__}: {e}")


@app.get("/api/status")
def status():
    return {"provider": llm.provider(), "dart": bool(__import__("os").getenv("DART_API_KEY"))}


@app.post("/api/scan")
def start_scan(p: ScanParams):
    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {"status": "running", "progress": 0.0, "message": "준비 중..."}
    threading.Thread(target=_run_scan, args=(job_id, p), daemon=True).start()
    return {"job": job_id}


@app.get("/api/scan/{job_id}")
def scan_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "job not found")
    return jobs[job_id]


@app.post("/api/analyze")
def analyze(p: AnalyzeParams):
    row = data.find_stock(p.query)
    if row is None:
        raise HTTPException(404, f"'{p.query}' 종목을 찾지 못했습니다.")
    res = report.analyze(report.gather(row.Code, row.Name, row.Market, row.Industry))
    res["llm_error"] = llm.last_error
    return res


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
