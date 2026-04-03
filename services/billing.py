from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class BillingError(RuntimeError):
    pass


@dataclass(frozen=True)
class BillingSummary:
    currency: str | None
    today_cost: float
    last_7_days_cost: float
    month_to_date_cost: float


def fetch_billing_summary(*, api_key: str, now: datetime | None = None) -> BillingSummary:
    if not api_key.strip():
        raise BillingError("Set 'openai_api_key' in the add-on config to fetch official spend.")

    current = now or datetime.now().astimezone()
    month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    last_7_days_start = today_start - timedelta(days=6)

    data = _fetch_cost_buckets(
        api_key=api_key,
        start_time=int(month_start.timestamp()),
        end_time=int(current.timestamp()),
        limit=max(1, (current.date() - month_start.date()).days + 1),
    )

    currency: str | None = None
    today_cost = 0.0
    last_7_days_cost = 0.0
    month_to_date_cost = 0.0

    for bucket in data.get("data", []):
        if not isinstance(bucket, dict):
            continue
        bucket_start = _as_datetime(bucket.get("start_time"))
        bucket_end = _as_datetime(bucket.get("end_time"))
        if bucket_start is None or bucket_end is None:
            continue

        bucket_cost, bucket_currency = _bucket_cost(bucket)
        if bucket_currency:
            currency = bucket_currency

        if _ranges_overlap(bucket_start, bucket_end, month_start, current):
            month_to_date_cost += bucket_cost
        if _ranges_overlap(bucket_start, bucket_end, last_7_days_start, current):
            last_7_days_cost += bucket_cost
        if _ranges_overlap(bucket_start, bucket_end, today_start, current):
            today_cost += bucket_cost

    return BillingSummary(
        currency=currency,
        today_cost=today_cost,
        last_7_days_cost=last_7_days_cost,
        month_to_date_cost=month_to_date_cost,
    )


def _fetch_cost_buckets(*, api_key: str, start_time: int, end_time: int, limit: int) -> dict[str, Any]:
    query = urlencode(
        {
            "start_time": start_time,
            "end_time": end_time,
            "bucket_width": "1d",
            "limit": limit,
        }
    )
    request = Request(
        url=f"https://api.openai.com/v1/organization/costs?{query}",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        message = _extract_error_message(error)
        raise BillingError(
            "Could not fetch official OpenAI costs. "
            "This endpoint usually requires an organization admin key. "
            f"API response: {message}"
        ) from error
    except URLError as error:
        raise BillingError(f"Could not reach OpenAI billing API: {error}") from error
    except OSError as error:
        raise BillingError(f"Could not read OpenAI billing response: {error}") from error

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise BillingError(f"OpenAI billing response was not valid JSON: {error}") from error

    if not isinstance(data, dict):
        raise BillingError("OpenAI billing response was not a JSON object.")
    return data


def _extract_error_message(error: HTTPError) -> str:
    try:
        payload = error.read().decode("utf-8")
        data = json.loads(payload)
        if isinstance(data, dict):
            body_error = data.get("error")
            if isinstance(body_error, dict):
                message = body_error.get("message")
                if isinstance(message, str) and message.strip():
                    return message
        return payload
    except Exception:
        return str(error)


def _bucket_cost(bucket: dict[str, Any]) -> tuple[float, str | None]:
    total = 0.0
    currency: str | None = None
    results = bucket.get("results", [])
    if not isinstance(results, list):
        return total, currency

    for result in results:
        if not isinstance(result, dict):
            continue
        amount = result.get("amount")
        if not isinstance(amount, dict):
            continue
        value = amount.get("value")
        bucket_currency = amount.get("currency")
        if isinstance(value, (int, float)):
            total += float(value)
        if isinstance(bucket_currency, str) and bucket_currency.strip():
            currency = bucket_currency

    return total, currency


def _as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(float(value)).astimezone()


def _ranges_overlap(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a
