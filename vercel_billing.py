"""Vercel billing, Pro credit, and invoice estimates for the desktop dashboard."""

from __future__ import annotations

import calendar
import gzip
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

API_BASE = "https://api.vercel.com"
DEFAULT_USD_MNT = 3500.0
PRO_CREDIT_USD = 20.0
SUBSCRIPTION_CATEGORY = "subscription licenses"
PLAN_BILLABLE_ITEMS = {"pro", "enterprise"}

PAID_STATES = {"paid", "succeeded", "settled", "completed"}


class VercelApiError(Exception):
    pass


def fmt_usd(value: float) -> str:
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


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


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _http_error(exc: urllib.error.HTTPError) -> VercelApiError:
    messages = {
        400: "Vercel API хүсэлт буруу байна (400). Огноо эсвэл Team ID-г шалгана уу.",
        401: "Vercel API token буруу эсвэл хүчингүй байна (401).",
        403: "Vercel billing API-д хандах эрхгүй (403). Pro/Enterprise team болон Billing/Usage role шаардлагатай.",
        404: "Vercel team эсвэл billing endpoint олдсонгүй (404). Team ID/Slug-аа шалгана уу.",
        409: "Vercel billing API төлөвтэй зөрчилдлөө (409).",
        410: "Vercel billing өгөгдөл байхгүй байна (410).",
        429: "Vercel API хязгаарт хүрлээ (429). Түр хүлээнэ үү.",
    }
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8", errors="replace"))
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        elif isinstance(body, dict):
            detail = str(body.get("message") or error or "")
    except (ValueError, OSError):
        detail = ""
    message = messages.get(exc.code)
    if message is None:
        message = f"Vercel API алдаа ({exc.code})" + (f": {detail}" if detail else ".")
    elif detail:
        message = f"{message} {detail}"
    return VercelApiError(message)


def _request_json(
    path: str,
    params: dict[str, Any],
    api_token: str,
    timeout: float = 20.0,
) -> Any:
    key = api_token.strip()
    if not key:
        raise VercelApiError("Vercel API token оруулаагүй байна.")
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"{API_BASE}{path}" + (f"?{query}" if query else "")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "ProjectRevenueDesktop/4.1",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise VercelApiError(f"Vercel API холбогдсонгүй: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise VercelApiError(f"Vercel API хариу уншихад алдаа: {exc}") from exc

    try:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8", errors="replace")) if raw else None
    except (OSError, ValueError) as exc:
        raise VercelApiError(f"Vercel API хариу задлахад алдаа: {exc}") from exc


def parse_charges(text: str) -> list[dict[str, Any]]:
    body = text.lstrip("\ufeff").strip()
    if not body:
        return []
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("charges", "data", "records"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        return [payload] if payload else []
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise VercelApiError("Vercel API хариу JSON форматтай биш байна.") from exc
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):
            rows.extend(row for row in item if isinstance(row, dict))
    return rows


def _request_charges(api_token: str, params: dict[str, Any], timeout: float = 20.0) -> list[dict[str, Any]]:
    key = api_token.strip()
    if not key:
        raise VercelApiError("Vercel API token оруулаагүй байна.")
    url = f"{API_BASE}/v1/billing/charges?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/jsonl",
            "Accept-Encoding": "identity",
            "User-Agent": "ProjectRevenueDesktop/4.1",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            encoding = (response.headers.get("Content-Encoding") or "").strip().lower()
    except urllib.error.HTTPError as exc:
        raise _http_error(exc) from exc
    except urllib.error.URLError as exc:
        raise VercelApiError(f"Vercel API холбогдсонгүй: {exc.reason}") from exc
    except (OSError, ValueError) as exc:
        raise VercelApiError(f"Vercel API хариу уншихад алдаа: {exc}") from exc

    try:
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        return parse_charges(raw.decode("utf-8", errors="replace"))
    except OSError as exc:
        raise VercelApiError(f"Vercel API хариу задлахад алдаа: {exc}") from exc


def _tag_value(tags: Any, wanted: tuple[str, ...]) -> str:
    if not isinstance(tags, dict):
        return ""
    normalized: dict[str, str] = {}
    for key, value in tags.items():
        if value is None:
            continue
        normalized[str(key).strip().lower().replace("_", "").replace("-", "")] = str(value).strip()
    for name in wanted:
        value = normalized.get(name)
        if value:
            return value
    for key, value in normalized.items():
        if value and (key.endswith("projectname") or key.endswith("project")):
            return value
    return ""


def month_range(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(timezone.utc)
    start = current.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start, current.astimezone(timezone.utc)


def summarize_charges(rows: list[dict[str, Any]], usd_mnt_rate: float = DEFAULT_USD_MNT) -> dict[str, Any]:
    billed_total = Decimal("0")
    effective_total = Decimal("0")
    usage_total = Decimal("0")
    usage_billed_total = Decimal("0")
    subscription_total = Decimal("0")
    subscription_billed_total = Decimal("0")
    non_credit_total = Decimal("0")
    category_totals: dict[str, Decimal] = {}
    services: dict[str, dict[str, Any]] = {}
    subscriptions: dict[str, dict[str, Any]] = {}
    projects: dict[str, Decimal] = {}
    projects_billed: dict[str, Decimal] = {}
    daily: dict[str, Decimal] = {}
    usage_lines = 0

    for row in rows:
        if not isinstance(row, dict):
            continue
        billed = _decimal(row.get("BilledCost"))
        effective = _decimal(row.get("EffectiveCost"))
        if row.get("EffectiveCost") in (None, ""):
            effective = billed
        billed_total += billed
        effective_total += effective
        category = str(row.get("ChargeCategory") or "Usage").strip() or "Usage"
        category_key = category.lower()
        is_subscription = str(row.get("ServiceCategory") or "").strip().lower() == SUBSCRIPTION_CATEGORY
        category_totals[category] = category_totals.get(category, Decimal("0")) + billed
        if is_subscription:
            subscription_total += effective
            subscription_billed_total += billed
        if category_key == "usage" and not is_subscription:
            usage_total += effective
            usage_billed_total += billed
            usage_lines += 1
        if category_key != "credit":
            non_credit_total += billed

        service_name = str(row.get("ServiceName") or "Vercel").strip() or "Vercel"
        service_bucket = subscriptions if is_subscription else services
        service = service_bucket.setdefault(
            service_name,
            {"name": service_name, "usd": Decimal("0"), "billed": Decimal("0"), "category": category, "lines": 0},
        )
        service["usd"] += effective
        service["billed"] += billed
        service["lines"] += 1

        project_name = _tag_value(
            row.get("Tags"),
            ("projectname", "vercelprojectname", "project"),
        )
        if project_name:
            projects[project_name] = projects.get(project_name, Decimal("0")) + effective
            projects_billed[project_name] = projects_billed.get(project_name, Decimal("0")) + billed

        day = str(row.get("ChargePeriodStart") or "").strip()[:10]
        if day and not is_subscription:
            daily[day] = daily.get(day, Decimal("0")) + effective

    rate = float(usd_mnt_rate)
    def service_rows(source: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        rows_out = [
            {
                "name": item["name"],
                "usd": float(item["usd"]),
                "billedUsd": float(item["billed"]),
                "mnt": round(float(item["usd"]) * rate),
                "category": item["category"],
                "lines": item["lines"],
            }
            for item in source.values()
        ]
        rows_out.sort(key=lambda item: item["usd"], reverse=True)
        return rows_out

    service_rows_out = service_rows(services)
    subscription_rows = service_rows(subscriptions)

    project_rows = [
        {
            "name": name,
            "usd": float(value),
            "billedUsd": float(projects_billed.get(name, Decimal("0"))),
            "mnt": round(float(value) * rate),
        }
        for name, value in projects.items()
    ]
    project_rows.sort(key=lambda item: item["usd"], reverse=True)
    daily_rows = [
        {"date": day, "usd": float(value), "mnt": round(float(value) * rate)}
        for day, value in sorted(daily.items())
    ]
    category_rows = [
        {"name": name, "usd": float(value), "mnt": round(float(value) * rate)}
        for name, value in sorted(category_totals.items(), key=lambda pair: pair[1], reverse=True)
    ]

    total_usd = float(billed_total)
    effective_usd = float(effective_total)
    return {
        "totalUsd": total_usd,
        "totalMnt": round(total_usd * rate),
        "effectiveUsd": effective_usd,
        "effectiveMnt": round(effective_usd * rate),
        "usageUsd": float(usage_total),
        "usageMnt": round(float(usage_total) * rate),
        "usageEffectiveUsd": float(usage_total),
        "usageBilledUsd": float(usage_billed_total),
        "usageLines": usage_lines,
        "subscriptionUsd": float(subscription_total),
        "subscriptionMnt": round(float(subscription_total) * rate),
        "subscriptionBilledUsd": float(subscription_billed_total),
        "nonCreditUsd": float(non_credit_total),
        "chargeCount": len(rows),
        "services": service_rows_out,
        "subscriptionServices": subscription_rows,
        "projects": project_rows,
        "daily": daily_rows,
        "categories": category_rows,
    }


def _invoice_amount_usd(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return round(value / 100.0, 2)
    if isinstance(value, float):
        return round(value, 2)
    text = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not text:
        return None
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if "." in text:
        return round(float(amount), 2)
    if amount < 100:
        return round(float(amount), 2)
    return round(float(amount) / 100.0, 2)


def _invoice_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("invoices", "data", "records", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if payload.get("id") or payload.get("invoiceId"):
            return [payload]
    return []


def parse_invoices(payload: Any) -> list[dict[str, Any]]:
    invoices: list[dict[str, Any]] = []
    for row in _invoice_rows(payload):
        status = str(
            row.get("state")
            or row.get("status")
            or row.get("paymentStatus")
            or row.get("payment_status")
            or ""
        ).strip().lower()
        period = row.get("period") if isinstance(row.get("period"), dict) else {}
        transitions = row.get("statusTransitions") if isinstance(row.get("statusTransitions"), dict) else {}
        paid_at = (
            transitions.get("paidAt")
            or row.get("paidAt")
            or row.get("paid_at")
            or row.get("paymentDate")
            or row.get("payment_date")
        )
        created_at = (
            row.get("createdAt")
            or row.get("created")
            or row.get("created_at")
            or row.get("issuedAt")
            or row.get("issued_at")
        )
        is_paid = status in PAID_STATES or bool(row.get("paid")) or bool(paid_at)
        amount = None
        for key in ("total", "totalDue", "total_due", "amount", "paidTotal", "paid_total"):
            amount = _invoice_amount_usd(row.get(key))
            if amount is not None:
                break
        if amount is None:
            continue
        source = str(row.get("invoiceSource") or row.get("invoice_source") or "").strip().lower()
        raw_items = row.get("lineItems") or row.get("line_items") or []
        if not isinstance(raw_items, list):
            raw_items = []
        items: list[dict[str, Any]] = []
        plan_usd = 0.0
        other_usd = 0.0
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            item_amount = None
            for key in ("amount", "subtotal", "total"):
                item_amount = _invoice_amount_usd(entry.get(key))
                if item_amount is not None:
                    break
            if item_amount is None:
                continue
            billable = str(entry.get("billableItem") or entry.get("billable_item") or "").strip().lower()
            title = str(entry.get("title") or entry.get("description") or "").strip()
            is_plan = billable in PLAN_BILLABLE_ITEMS or (not billable and title.lower() in PLAN_BILLABLE_ITEMS)
            if is_plan:
                plan_usd += item_amount
            else:
                other_usd += item_amount
            items.append({"name": title or billable or "Vercel", "usd": item_amount, "plan": is_plan})
        if abs((plan_usd + other_usd) - amount) > 0.005:
            other_usd += amount - plan_usd - other_usd
        other_usd = max(other_usd, 0.0)
        if plan_usd > 0:
            kind = "plan"
        elif "domain" in source or "registrar" in source:
            kind = "domain"
        elif amount <= 0:
            kind = "zero"
        else:
            kind = "other"
        period_start = (
            period.get("start")
            or row.get("periodStart")
            or row.get("period_start")
            or created_at
        )
        period_end = (
            period.get("end")
            or row.get("periodEnd")
            or row.get("period_end")
            or period_start
        )
        invoices.append(
            {
                "id": str(row.get("id") or row.get("invoiceId") or row.get("invoice_id") or ""),
                "number": str(
                    row.get("number")
                    or row.get("invoiceNumber")
                    or row.get("invoice_number")
                    or row.get("id")
                    or ""
                ),
                "status": status or ("paid" if is_paid else "unknown"),
                "paid": is_paid,
                "usd": amount,
                "planUsd": round(plan_usd, 2),
                "otherUsd": round(other_usd, 2),
                "kind": kind,
                "source": source,
                "items": items,
                "periodStart": str(period_start or ""),
                "periodEnd": str(period_end or ""),
                "paidAt": str(paid_at or ""),
                "created": str(created_at or ""),
                "currency": str(row.get("currency") or row.get("Currency") or "USD"),
            }
        )
    invoices.sort(
        key=lambda item: (
            str(item.get("paidAt") or ""),
            str(item.get("periodEnd") or ""),
            str(item.get("created") or ""),
        ),
        reverse=True,
    )
    return invoices


def fetch_invoices(
    api_token: str,
    team_id: str = "",
    slug: str = "",
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], str]:
    params: dict[str, Any] = {"limit": 12}
    team = team_id.strip()
    if team:
        params["teamId"] = team
    elif slug.strip():
        params["slug"] = slug.strip()
    try:
        payload = _request_json("/v1/invoices", params, api_token, timeout)
    except VercelApiError as exc:
        return [], str(exc)
    return parse_invoices(payload), ""


def parse_credit_ledger(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    ledgers = payload.get("creditLedgers") or payload.get("credit_ledgers") or []
    if not isinstance(ledgers, list) or not ledgers:
        return None
    ledger = ledgers[0] if isinstance(ledgers[0], dict) else {}
    total = _number(ledger.get("total") or ledger.get("allocated"))
    remaining = _number(ledger.get("remaining"))
    if total <= 0 and remaining <= 0:
        return None
    used = max(total - remaining, 0.0)
    return {
        "allocatedUsd": round(total, 2),
        "usedUsd": round(used, 2),
        "remainingUsd": round(max(remaining, 0.0), 2),
        "cadence": str(payload.get("cadence") or ""),
        "title": str(ledger.get("title") or ""),
        "periodStart": str(ledger.get("periodStart") or ""),
        "periodEnd": str(ledger.get("periodEnd") or ""),
    }


def fetch_precommitment_credit(
    api_token: str,
    team_id: str = "",
    timeout: float = 20.0,
) -> tuple[dict[str, Any] | None, str]:
    team = team_id.strip()
    if not team:
        return None, "Team ID байхгүй тул credit ledger-ийг уншаагүй."
    try:
        payload = _request_json(
            "/v1/invoices/pre-commitment-usage",
            {"teamId": team},
            api_token,
            timeout,
        )
    except VercelApiError as exc:
        return None, str(exc)
    return parse_credit_ledger(payload), ""


def fetch_vercel_billing(
    api_token: str,
    team_id: str = "",
    slug: str = "",
    usd_mnt_rate: float = DEFAULT_USD_MNT,
    timeout: float = 20.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    key = api_token.strip()
    if not key:
        raise VercelApiError("Vercel API token оруулаагүй байна.")
    try:
        rate = float(usd_mnt_rate)
    except (TypeError, ValueError):
        rate = DEFAULT_USD_MNT
    if not 1 <= rate <= 100_000:
        rate = DEFAULT_USD_MNT

    start, end = month_range(now)
    params: dict[str, Any] = {"from": _iso(start), "to": _iso(end)}
    team = team_id.strip()
    team_slug = slug.strip()
    if team:
        params["teamId"] = team
    elif team_slug:
        params["slug"] = team_slug

    rows = _request_charges(key, params, timeout)
    summary = summarize_charges(rows, rate)
    invoices, invoice_error = fetch_invoices(key, team, team_slug, timeout)
    credit, credit_error = fetch_precommitment_credit(key, team, timeout)

    usage_usd = max(float(summary.get("usageUsd", 0) or 0), 0.0)
    allocated = PRO_CREDIT_USD
    used = min(usage_usd, allocated)
    remaining = max(allocated - usage_usd, 0.0)
    credit_source = "pro"
    if credit:
        allocated = float(credit["allocatedUsd"])
        used = float(credit["usedUsd"])
        remaining = float(credit["remainingUsd"])
        credit_source = "ledger"
    overage = max(usage_usd - allocated, 0.0)
    non_credit = max(float(summary.get("nonCreditUsd", 0) or 0), 0.0)
    usage_billed = max(float(summary.get("usageBilledUsd", 0) or 0), 0.0)
    credit_applied = min(usage_usd, allocated)
    credit_in_billed = usage_billed < usage_usd - 0.01
    estimated_invoice = max(non_credit - (0.0 if credit_in_billed else credit_applied), 0.0)

    paid_invoices = [item for item in invoices if item.get("paid")]
    paid_total = sum(float(item["usd"]) for item in paid_invoices)
    paid_plan_total = sum(float(item.get("planUsd", 0) or 0) for item in paid_invoices)
    paid_other_total = sum(float(item.get("otherUsd", 0) or 0) for item in paid_invoices)
    paid_plan_count = sum(1 for item in paid_invoices if float(item.get("planUsd", 0) or 0) > 0)
    latest_paid = paid_invoices[0] if paid_invoices else None
    latest_plan = next((item for item in paid_invoices if float(item.get("planUsd", 0) or 0) > 0), None)
    if paid_invoices:
        billing_cost = paid_total
        invoice_source = "paid"
    else:
        billing_cost = estimated_invoice
        invoice_source = "estimate"

    elapsed_days = max((end - start).total_seconds() / 86400.0, 1.0 / 24.0)
    month_days = calendar.monthrange(start.year, start.month)[1]
    projected_usage = usage_usd * month_days / elapsed_days
    projected_overage = max(projected_usage - allocated, 0.0)
    projected_invoice = max(estimated_invoice + projected_overage - overage, 0.0)
    if team:
        scope = f"Team ID · {team}"
    elif team_slug:
        scope = f"Team · {team_slug}"
    else:
        scope = "Хувийн account"

    summary.update(
        {
            "ok": True,
            "generatedAt": _iso(end),
            "periodStart": _iso(start),
            "periodEnd": _iso(end),
            "scope": scope,
            "teamId": team,
            "slug": team_slug,
            "usdMntRate": rate,
            "daysElapsed": elapsed_days,
            "monthDays": month_days,
            "creditAllocatedUsd": allocated,
            "creditUsedUsd": used,
            "creditRemainingUsd": remaining,
            "creditUsedPct": (used / allocated * 100.0) if allocated > 0 else 0.0,
            "creditOverageUsd": overage,
            "creditSource": credit_source,
            "creditError": credit_error,
            "creditPeriodStart": (credit or {}).get("periodStart", ""),
            "creditPeriodEnd": (credit or {}).get("periodEnd", ""),
            "estimatedInvoiceUsd": estimated_invoice,
            "estimatedInvoiceMnt": round(estimated_invoice * rate),
            "billingCostUsd": billing_cost,
            "billingCostMnt": round(billing_cost * rate),
            "invoiceSource": invoice_source,
            "invoicePaid": bool(paid_invoices),
            "paidInvoiceTotalUsd": paid_total,
            "paidInvoiceTotalMnt": round(paid_total * rate),
            "paidPlanInvoiceTotalUsd": paid_plan_total,
            "paidPlanInvoiceTotalMnt": round(paid_plan_total * rate),
            "paidPlanInvoiceCount": paid_plan_count,
            "paidOtherInvoiceTotalUsd": paid_other_total,
            "paidOtherInvoiceTotalMnt": round(paid_other_total * rate),
            "latestPaidInvoiceUsd": float((latest_paid or {}).get("usd", estimated_invoice)),
            "latestPlanInvoiceUsd": float((latest_plan or {}).get("usd", 0.0)),
            "latestPlanInvoiceNumber": (latest_plan or {}).get("number", ""),
            "latestPlanInvoicePaidAt": (latest_plan or {}).get("paidAt", ""),
            "invoiceBreakdown": [
                {
                    "number": item.get("number", ""),
                    "usd": float(item.get("usd", 0) or 0),
                    "planUsd": float(item.get("planUsd", 0) or 0),
                    "otherUsd": float(item.get("otherUsd", 0) or 0),
                    "kind": item.get("kind", ""),
                    "paidAt": item.get("paidAt", ""),
                }
                for item in paid_invoices
            ],
            "invoiceNumber": (latest_paid or {}).get("number", ""),
            "invoicePeriodStart": (latest_paid or {}).get("periodStart", ""),
            "invoicePeriodEnd": (latest_paid or {}).get("periodEnd", ""),
            "invoicePaidAt": (latest_paid or {}).get("paidAt", ""),
            "invoiceCount": len(invoices),
            "paidInvoiceCount": len(paid_invoices),
            "invoiceError": invoice_error,
            "projectedUsageUsd": projected_usage,
            "projectedOverageUsd": projected_overage,
            "projectedInvoiceUsd": projected_invoice,
            "projectedInvoiceMnt": round(projected_invoice * rate),
            "projectedUsd": projected_invoice,
            "projectedMnt": round(projected_invoice * rate),
            "dailyAvgUsd": usage_usd / elapsed_days,
            "dataNote": (
                "Vercel FOCUS charges + Pro сарын $20 credit. Credit usage нь ChargeCategory=Usage EffectiveCost, "
                "Subscription Licenses (Pro, seats, add-ons)-ийг хассан infra usage. BilledCost нь credit хассан дүн. "
                "Төлсөн нэхэмжлэлүүдийн нийт дүнг /v1/invoices-ээс зардал болгоно; Pro subscription болон "
                "бусад (домэйн гэх мэт) төлбөрийг тусад нь харуулна. Төлсөн нэхэмжлэл байхгүй бол credit хассан "
                "тооцоог харуулна."
            ),
        }
    )
    return summary

