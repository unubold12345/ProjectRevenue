from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_API_URL = "https://lawtest-rho.vercel.app"
DEFAULT_PROJECT_NAME = "Lexlab"
DEFAULT_NEON_RATE = 3500.0
DEFAULT_VERCEL_RATE = 3500.0
UB = timezone(timedelta(hours=8))


class RevenueApiError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def new_project_id() -> str:
    return uuid.uuid4().hex[:12]


def clean_project(raw: Any, index: int = 0) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    api_url = str(raw.get("apiUrl") or "").strip()
    api_key = str(raw.get("apiKey") or "").strip()
    if not api_url:
        return None
    project_id = str(raw.get("id") or "").strip() or new_project_id()
    return {
        "id": project_id,
        "name": (name or f"Project {index + 1}")[:60],
        "apiUrl": api_url,
        "apiKey": api_key,
    }


def clean_neon(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    try:
        rate = float(data.get("usdMntRate") or DEFAULT_NEON_RATE)
    except (TypeError, ValueError):
        rate = DEFAULT_NEON_RATE
    if not 1 <= rate <= 100_000:
        rate = DEFAULT_NEON_RATE
    return {
        "apiKey": str(data.get("apiKey") or "").strip(),
        "orgId": str(data.get("orgId") or "").strip(),
        "projectIds": str(data.get("projectIds") or "").strip(),
        "usdMntRate": rate,
    }


def clean_vercel(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    try:
        rate = float(data.get("usdMntRate") or DEFAULT_VERCEL_RATE)
    except (TypeError, ValueError):
        rate = DEFAULT_VERCEL_RATE
    if not 1 <= rate <= 100_000:
        rate = DEFAULT_VERCEL_RATE
    return {
        "apiToken": str(data.get("apiToken") or "").strip(),
        "teamId": str(data.get("teamId") or "").strip(),
        "slug": str(data.get("slug") or "").strip(),
        "usdMntRate": rate,
    }


def load_config() -> dict[str, Any]:
    projects: list[dict[str, str]] = []
    active_id = ""
    neon = clean_neon(None)
    vercel = clean_vercel(None)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}

    if isinstance(raw, dict):
        neon = clean_neon(raw.get("neon"))
        vercel = clean_vercel(raw.get("vercel"))
        if isinstance(raw.get("projects"), list):
            for index, item in enumerate(raw["projects"]):
                project = clean_project(item, index)
                if project is not None:
                    projects.append(project)
            active_id = str(raw.get("activeProjectId") or "").strip()
        elif raw.get("apiUrl"):
            project = clean_project(
                {
                    "name": DEFAULT_PROJECT_NAME,
                    "apiUrl": raw.get("apiUrl"),
                    "apiKey": raw.get("apiKey"),
                }
            )
            if project is not None:
                projects.append(project)

    if not projects:
        projects.append(
            {
                "id": "lexlab",
                "name": DEFAULT_PROJECT_NAME,
                "apiUrl": DEFAULT_API_URL,
                "apiKey": "",
            }
        )
    if not any(project["id"] == active_id for project in projects):
        active_id = projects[0]["id"]

    env_url = (os.environ.get("REVENUE_API_URL") or os.environ.get("LEXLAB_API_URL") or "").strip()
    env_key = (os.environ.get("REVENUE_API_KEY") or os.environ.get("LEXLAB_API_KEY") or "").strip()
    if env_url or env_key:
        for project in projects:
            if project["id"] == active_id:
                if env_url:
                    project["apiUrl"] = env_url
                if env_key:
                    project["apiKey"] = env_key

    neon_key = (os.environ.get("NEON_API_KEY") or "").strip()
    neon_org = (os.environ.get("NEON_ORG_ID") or "").strip()
    neon_projects = (os.environ.get("NEON_PROJECT_IDS") or "").strip()
    neon_rate = (os.environ.get("NEON_USD_MNT") or "").strip()
    if neon_key:
        neon["apiKey"] = neon_key
    if neon_org:
        neon["orgId"] = neon_org
    if neon_projects:
        neon["projectIds"] = neon_projects
    if neon_rate:
        neon["usdMntRate"] = clean_neon({"usdMntRate": neon_rate})["usdMntRate"]

    vercel_token = (os.environ.get("VERCEL_API_TOKEN") or os.environ.get("VERCEL_TOKEN") or "").strip()
    vercel_team = (os.environ.get("VERCEL_TEAM_ID") or "").strip()
    vercel_slug = (os.environ.get("VERCEL_TEAM_SLUG") or "").strip()
    vercel_rate = (os.environ.get("VERCEL_USD_MNT") or "").strip()
    if vercel_token:
        vercel["apiToken"] = vercel_token
    if vercel_team:
        vercel["teamId"] = vercel_team
    if vercel_slug:
        vercel["slug"] = vercel_slug
    if vercel_rate:
        vercel["usdMntRate"] = clean_vercel({"usdMntRate": vercel_rate})["usdMntRate"]

    return {"projects": projects, "activeProjectId": active_id, "neon": neon, "vercel": vercel}


def save_config(config: dict[str, Any]) -> None:
    projects: list[dict[str, str]] = []
    raw_projects = config.get("projects") if isinstance(config, dict) else None
    if isinstance(raw_projects, list):
        for index, item in enumerate(raw_projects):
            project = clean_project(item, index)
            if project is not None:
                projects.append(project)
    active_id = str((config or {}).get("activeProjectId") or "").strip()
    if not any(project["id"] == active_id for project in projects):
        active_id = projects[0]["id"] if projects else ""
    neon = clean_neon((config or {}).get("neon"))
    vercel = clean_vercel((config or {}).get("vercel"))
    payload = {
        "version": 4,
        "projects": projects,
        "activeProjectId": active_id,
        "neon": neon,
        "vercel": vercel,
    }
    CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def active_project(config: dict[str, Any]) -> dict[str, str] | None:
    projects = config.get("projects") if isinstance(config, dict) else None
    if not isinstance(projects, list) or not projects:
        return None
    active_id = str((config or {}).get("activeProjectId") or "")
    for project in projects:
        if project.get("id") == active_id:
            return project
    return projects[0]


def revenue_endpoint(api_url: str) -> str:
    base = api_url.strip().rstrip("/")
    if not base:
        raise RevenueApiError("API хаяг хоосон байна.")
    if base.endswith("/api/revenue"):
        return base
    return f"{base}/api/revenue"


def fetch_summary(api_url: str, api_key: str, timeout: float = 15.0) -> dict[str, Any]:
    if not api_key.strip():
        raise RevenueApiError("API түлхүүр оруулаагүй байна.")
    request = urllib.request.Request(
        revenue_endpoint(api_url),
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Accept": "application/json",
            "User-Agent": "ProjectRevenueDesktop/2.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        messages = {
            401: "API түлхүүр буруу байна (401).",
            404: "API хаяг олдсонгүй (404). URL-аа шалгана уу.",
            503: "Сервер дээр REVENUE_API_KEY тохируулаагүй байна (503).",
        }
        raise RevenueApiError(messages.get(status, f"Сервер алдаа буцаалаа ({status})."), status) from exc
    except urllib.error.URLError as exc:
        raise RevenueApiError("Серверт холбогдож чадсангүй. Интернэт болон API хаягаа шалгана уу.") from exc
    except (ValueError, UnicodeDecodeError) as exc:
        raise RevenueApiError("Серверийн хариу буруу форматтай байна.") from exc

    if not isinstance(payload, dict):
        raise RevenueApiError("Серверийн хариу буруу байна.")
    all_time = payload.get("allTime")
    current = payload.get("current")
    series = payload.get("series")
    if not isinstance(all_time, dict) or not isinstance(current, dict) or not isinstance(series, list):
        raise RevenueApiError("Серверийн хариу дутуу байна.")
    return payload


def fmt_money(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    return f"{number:,}".replace(",", " ") + "₮"


def fmt_short(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    sign = "-" if number < 0 else ""
    number = abs(number)
    if number >= 1_000_000_000:
        return f"{sign}{number / 1_000_000_000:.1f} тэрбум"
    if number >= 1_000_000:
        return f"{sign}{number / 1_000_000:.1f} сая"
    if number >= 10_000:
        return f"{sign}{number / 1_000:.0f} мян"
    return f"{sign}{number:,.0f}".replace(",", " ")


def fmt_month(month: str) -> str:
    return month.replace("-", ".")


def month_name(month: str) -> str:
    try:
        return f"{int(month.split('-')[1])}-р сар"
    except (IndexError, ValueError):
        return month


def fmt_time(value: Any) -> str:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        stamp = datetime.now(timezone.utc)
    return stamp.astimezone(UB).strftime("%Y.%m.%d %H:%M:%S") + " (УБ)"


def nice_ceiling(value: float) -> float:
    if value <= 0:
        return 1.0
    import math

    magnitude = 10 ** math.floor(math.log10(value))
    normalized = value / magnitude
    for step in (1, 2, 2.5, 5, 10):
        if normalized <= step:
            return step * magnitude
    return 10 * magnitude
