"""Neon consumption-based billing estimate for the desktop dashboard."""

from __future__ import annotations

import calendar
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

API_BASE = "https://console.neon.tech/api/v2"
DEFAULT_USD_MNT = 3500.0
METRICS = (
    "compute_unit_seconds",
    "root_branch_bytes_month",
    "child_branch_bytes_month",
    "instant_restore_bytes_month",
    "snapshot_storage_bytes_month",
    "public_network_transfer_bytes",
    "private_network_transfer_bytes",
    "extra_branches_month",
)
PLAN_RATES: dict[str, dict[str, float]] = {
    "launch": {"compute": 0.106, "root": 0.35, "child": 0.35, "instant": 0.20, "snapshot": 0.09, "public": 0.10, "private": 0.0, "branches": 1.50},
    "scale": {"compute": 0.222, "root": 0.35, "child": 0.35, "instant": 0.20, "snapshot": 0.09, "public": 0.10, "private": 0.01, "branches": 1.50},
    "agent": {"compute": 0.106, "root": 0.35, "child": 0.35, "instant": 0.20, "snapshot": 0.09, "public": 0.10, "private": 0.01, "branches": 1.50},
    "enterprise": {"compute": 0.222, "root": 0.35, "child": 0.35, "instant": 0.20, "snapshot": 0.09, "public": 0.10, "private": 0.01, "branches": 1.50},
}
FREE_BRANCHES = {"launch": 10, "scale": 25, "agent": 25, "enterprise": 25}
PUBLIC_FREE_GB = 500.0


class NeonApiError(Exception):
    pass


def fmt_usd(value: float) -> str:
    if value < 0:
        value = 0
    return f"${value:,.2f}"


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _request(path: str, api_key: str, params: dict[str, Any] | None = None, timeout: float = 20.0) -> dict[str, Any]:
    key = api_key.strip()
    if not key:
        raise NeonApiError("Neon API түлхүүр оруулаагүй байна.")
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "ProjectRevenueDesktop/3.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        messages = {
            401: "Neon API түлхүүр буруу эсвэл хүчингүй байна (401).",
            403: "Энэ Neon төсөл consumption API дэмжихгүй байна (403). Free планд боломжгүй.",
            404: "Organization олдсонгүй (404). Org ID-г шалгана уу.",
            406: "Огнооны хүрээ буруу байна (406).",
            429: "Neon API хязгаарт хүрлээ (429). Түр хүлээнэ үү.",
        }
        message = messages.get(exc.code)
        if message is None:
            try:
                body = json.loads(exc.read().decode("utf-8"))
                message = str(body.get("message") or body.get("error") or "")
            except (ValueError, OSError):
                message = ""
            message = f"Neon API алдаа ({exc.code})" + (f": {message}" if message else ".")
        raise NeonApiError(message) from exc
    except urllib.error.URLError as exc:
        raise NeonApiError(f"Neon API холбогдсонгүй: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise NeonApiError(f"Neon API хариу уншихад алдаа: {exc}") from exc


def _org_list(api_key: str, timeout: float) -> list[dict[str, Any]]:
    payload = _request("/users/me/organizations", api_key, timeout=timeout)
    rows = payload.get("organizations") or []
    return [row for row in rows if isinstance(row, dict)]


def resolve_org(api_key: str, org_id: str = "", timeout: float = 20.0) -> tuple[str, str]:
    requested = org_id.strip()
    try:
        organizations = _org_list(api_key, timeout)
    except NeonApiError:
        if requested:
            return requested, requested
        raise
    if requested:
        for org in organizations:
            if str(org.get("id") or org.get("org_id") or "") == requested:
                return requested, str(org.get("name") or requested)
        return requested, requested
    if not organizations:
        raise NeonApiError("Neon organization олдсонгүй. Org ID-г тохиргоонд оруулна уу.")
    if len(organizations) > 1:
        names = ", ".join(str(org.get("name") or org.get("id") or "?") for org in organizations)
        raise NeonApiError(f"Олон Neon organization байна. Org ID-г оруулна уу: {names}")
    org = organizations[0]
    found = str(org.get("id") or org.get("org_id") or "").strip()
    if not found:
        raise NeonApiError("Neon organization ID олдсонгүй.")
    return found, str(org.get("name") or found)


def fetch_project_names(api_key: str, org_id: str, timeout: float = 20.0) -> dict[str, str]:
    try:
        payload = _request("/projects", api_key, {"org_id": org_id, "limit": 100}, timeout=timeout)
    except NeonApiError:
        return {}
    names: dict[str, str] = {}
    for row in payload.get("projects") or []:
        if not isinstance(row, dict):
            continue
        project_id = str(row.get("id") or "").strip()
        if project_id:
            names[project_id] = str(row.get("name") or project_id)
    return names


def fetch_spending_limit(api_key: str, org_id: str, timeout: float = 20.0) -> int | None:
    try:
        payload = _request(f"/organizations/{urllib.parse.quote(org_id)}/billing/spending_limit", api_key, timeout=timeout)
    except NeonApiError:
        return None
    value = payload.get("spending_limit_cents")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hours(start: Any, end: Any) -> float:
    first = _parse_time(start)
    last = _parse_time(end)
    if first is None or last is None or last <= first:
        return 24.0
    return (last - first).total_seconds() / 3600.0


def _metric_name(row: dict[str, Any]) -> str:
    return str(row.get("metric_name") or "")


def _metric_value(row: dict[str, Any]) -> float:
    try:
        return float(row.get("value") or 0)
    except (TypeError, ValueError):
        return 0.0


def summarize_consumption(payload: dict[str, Any], project_names: dict[str, str] | None = None, usd_mnt_rate: float = DEFAULT_USD_MNT) -> dict[str, Any]:
    names = project_names or {}
    projects_out: list[dict[str, Any]] = []
    grand = {"compute": 0.0, "storage": 0.0, "transfer": 0.0, "branches": 0.0}
    usage_total = {"compute_cu_hours": 0.0, "storage_gb_months": 0.0, "public_gb": 0.0, "private_gb": 0.0, "branch_months": 0.0}

    for project in payload.get("projects") or []:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("project_id") or "").strip()
        if not project_id:
            continue
        raw = {metric: 0.0 for metric in METRICS}
        billable_branch_hours = 0.0
        plans: list[str] = []
        for period in project.get("periods") or []:
            if not isinstance(period, dict):
                continue
            plan = str(period.get("period_plan") or "launch").strip().lower()
            if plan not in PLAN_RATES:
                plan = "launch"
            plans.append(plan)
            free_children = max(0, FREE_BRANCHES.get(plan, FREE_BRANCHES["launch"]) - 1)
            for bucket in period.get("consumption") or []:
                if not isinstance(bucket, dict):
                    continue
                bucket_values = {metric: 0.0 for metric in METRICS}
                for metric_row in bucket.get("metrics") or []:
                    if isinstance(metric_row, dict):
                        name = _metric_name(metric_row)
                        if name in bucket_values:
                            bucket_values[name] += _metric_value(metric_row)
                for name, value in bucket_values.items():
                    raw[name] += value
                hours = _hours(bucket.get("timeframe_start"), bucket.get("timeframe_end"))
                billable_branch_hours += max(0.0, bucket_values["extra_branches_month"] - free_children * hours)
        plan = plans[-1] if plans else "launch"
        rates = PLAN_RATES.get(plan, PLAN_RATES["launch"])
        compute_cu_hours = raw["compute_unit_seconds"] / 3600.0
        storage_gb_months = sum(raw[name] for name in ("root_branch_bytes_month", "child_branch_bytes_month", "instant_restore_bytes_month", "snapshot_storage_bytes_month")) / 1_000_000_000.0
        root_gb_months = raw["root_branch_bytes_month"] / 1_000_000_000.0
        child_gb_months = raw["child_branch_bytes_month"] / 1_000_000_000.0
        instant_gb_months = raw["instant_restore_bytes_month"] / 1_000_000_000.0
        snapshot_gb_months = raw["snapshot_storage_bytes_month"] / 1_000_000_000.0
        public_gb = raw["public_network_transfer_bytes"] / 1_000_000_000.0
        private_gb = raw["private_network_transfer_bytes"] / 1_000_000_000.0
        branch_months = billable_branch_hours / 744.0

        costs = {
            "compute": compute_cu_hours * rates["compute"],
            "storage": root_gb_months * rates["root"] + child_gb_months * rates["child"] + instant_gb_months * rates["instant"] + snapshot_gb_months * rates["snapshot"],
            "transfer": max(0.0, public_gb - PUBLIC_FREE_GB) * rates["public"] + private_gb * rates["private"],
            "branches": branch_months * rates["branches"],
        }
        total_usd = sum(costs.values())
        for key in grand:
            grand[key] += costs[key]
        usage_total["compute_cu_hours"] += compute_cu_hours
        usage_total["storage_gb_months"] += storage_gb_months
        usage_total["public_gb"] += public_gb
        usage_total["private_gb"] += private_gb
        usage_total["branch_months"] += branch_months
        projects_out.append(
            {
                "id": project_id,
                "name": names.get(project_id, project_id),
                "plan": plan,
                "usage": {
                    "compute_cu_hours": compute_cu_hours,
                    "storage_gb_months": storage_gb_months,
                    "root_gb_months": root_gb_months,
                    "child_gb_months": child_gb_months,
                    "instant_gb_months": instant_gb_months,
                    "snapshot_gb_months": snapshot_gb_months,
                    "public_gb": public_gb,
                    "private_gb": private_gb,
                    "branch_months": branch_months,
                },
                "costs": costs,
                "totalUsd": total_usd,
                "totalMnt": round(total_usd * usd_mnt_rate),
            }
        )

    total_usd = sum(grand.values())
    return {
        "projects": sorted(projects_out, key=lambda row: row["totalUsd"], reverse=True),
        "costs": grand,
        "usage": usage_total,
        "totalUsd": total_usd,
        "totalMnt": round(total_usd * usd_mnt_rate),
    }


def month_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    start = current.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, current.astimezone(timezone.utc)


def fetch_neon_billing(api_key: str, org_id: str = "", project_ids: str = "", usd_mnt_rate: float = DEFAULT_USD_MNT, timeout: float = 20.0) -> dict[str, Any]:
    key = api_key.strip()
    if not key:
        raise NeonApiError("Neon API түлхүүр оруулаагүй байна.")
    try:
        rate = float(usd_mnt_rate)
    except (TypeError, ValueError):
        rate = DEFAULT_USD_MNT
    if not 1 <= rate <= 100_000:
        rate = DEFAULT_USD_MNT

    resolved_org, org_name = resolve_org(key, org_id, timeout)
    start, end = month_range()
    params: dict[str, Any] = {
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": end.isoformat().replace("+00:00", "Z"),
        "granularity": "daily",
        "org_id": resolved_org,
        "metrics": ",".join(METRICS),
        "limit": 100,
    }
    selected = [item.strip() for item in project_ids.split(",") if item.strip()]
    if selected:
        params["project_ids"] = ",".join(selected[:100])

    rows: list[dict[str, Any]] = []
    cursor = ""
    for _ in range(10):
        if cursor:
            params["cursor"] = cursor
        payload = _request("/consumption_history/v2/projects", key, params, timeout=timeout)
        for row in payload.get("projects") or []:
            if isinstance(row, dict):
                rows.append(row)
        cursor = str((payload.get("pagination") or {}).get("cursor") or "")
        if not cursor:
            break

    names = fetch_project_names(key, resolved_org, timeout)
    summary = summarize_consumption({"projects": rows}, names, rate)
    elapsed_days = max((end - start).total_seconds() / 86400.0, 1.0 / 24.0)
    month_days = calendar.monthrange(start.year, start.month)[1]
    projected_usd = summary["totalUsd"] * month_days / elapsed_days
    limit_cents = fetch_spending_limit(key, resolved_org, timeout)
    summary.update(
        {
            "ok": True,
            "generatedAt": end.isoformat().replace("+00:00", "Z"),
            "periodStart": start.isoformat().replace("+00:00", "Z"),
            "periodEnd": end.isoformat().replace("+00:00", "Z"),
            "orgId": resolved_org,
            "orgName": org_name,
            "usdMntRate": rate,
            "daysElapsed": elapsed_days,
            "monthDays": month_days,
            "projectedUsd": projected_usd,
            "projectedMnt": round(projected_usd * rate),
            "dailyAvgUsd": summary["totalUsd"] / elapsed_days,
            "spendingLimitCents": limit_cents,
            "dataNote": "Neon consumption өгөгдөл (ихэвчлэн 15 мин тутам шинэчлэгдэнэ). Эцсийн нэхэмжлэл биш, тооцоолол.",
        }
    )
    return summary
