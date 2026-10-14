"""LLM 호출 래퍼. .env 또는 환경변수의 키로 엔진을 고른다 (ANALYZER_PROVIDER=openai|anthropic)."""
import json
import os
import re
from pathlib import Path


def load_env(path: Path = Path(__file__).parent / ".env") -> None:
    """KEY=VALUE 형식의 .env를 읽어 환경변수에 넣는다 (이미 있는 값은 유지)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


load_env()


def provider() -> str | None:
    want = os.getenv("ANALYZER_PROVIDER", "").lower()
    keys = {"openai": os.getenv("OPENAI_API_KEY"), "anthropic": os.getenv("ANTHROPIC_API_KEY")}
    if want in keys and keys[want]:
        return want
    return next((p for p, k in keys.items() if k), None)


def available() -> bool:
    return provider() is not None


def _complete(system: str, user: str, max_tokens: int) -> str:
    p = provider()
    if p == "openai":
        from openai import OpenAI

        r = OpenAI().chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return r.choices[0].message.content or ""
    import anthropic

    msg = anthropic.Anthropic().messages.create(
        model=os.getenv("ANALYZER_MODEL", "claude-sonnet-5-5"),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if b.type == "text")


last_error: str | None = None


def ask_json(system: str, user: str, max_tokens: int = 4000) -> dict | None:
    """JSON 객체 하나를 돌려받는다. 실패하면 None (호출 측에서 규칙 기반으로 대체)."""
    global last_error
    if not available():
        return None
    try:
        text = _complete(system + "\n반드시 JSON 객체 하나만 출력하세요.", user, max_tokens)
        m = re.search(r"\{.*\}", text, re.S)
        last_error = None
        return json.loads(m.group(0)) if m else None
    except Exception as e:  # 키 오류·한도 초과 등 -> 규칙 기반으로 대체, 화면에 사유 표시
        last_error = f"{type(e).__name__}: {str(e)[:200]}"
        return None
