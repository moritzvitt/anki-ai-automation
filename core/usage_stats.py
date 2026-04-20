from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


_ADDON_ROOT = Path(__file__).resolve().parent.parent
_USER_DATA_DIR = _ADDON_ROOT / "user_files" / "user_data"
_USAGE_FILE = _USER_DATA_DIR / "usage_stats.json"
_LEGACY_USAGE_FILE = _ADDON_ROOT / "user_data" / "usage_stats.json"


def load_usage_stats() -> dict[str, Any]:
    _migrate_legacy_usage_file()
    if not _USAGE_FILE.exists():
        return _default_usage_stats()

    try:
        with _USAGE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return _default_usage_stats()

    if not isinstance(data, dict):
        return _default_usage_stats()
    return _merge_defaults(data)


def record_usage_run(
    *,
    model: str,
    note_count: int,
    request_count: int,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    total_tokens: int,
    estimated_cost_usd: float | None,
    history_limit: int,
) -> None:
    _migrate_legacy_usage_file()
    stats = load_usage_stats()
    _increment_totals(
        stats["totals"],
        note_count=note_count,
        request_count=request_count,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )

    by_model = stats["by_model"].setdefault(model, _empty_totals())
    _increment_totals(
        by_model,
        note_count=note_count,
        request_count=request_count,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )

    stats["recent_runs"].insert(
        0,
        {
            "timestamp": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "model": model,
            "note_count": note_count,
            "request_count": request_count,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
        },
    )
    stats["recent_runs"] = stats["recent_runs"][:history_limit]

    _USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _USAGE_FILE.open("w", encoding="utf-8") as handle:
        json.dump(stats, handle, indent=2, sort_keys=True)


def _migrate_legacy_usage_file() -> None:
    if not _LEGACY_USAGE_FILE.exists() or _USAGE_FILE.exists():
        return
    _USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    _USAGE_FILE.write_bytes(_LEGACY_USAGE_FILE.read_bytes())


def build_usage_report(stats: dict[str, Any]) -> str:
    totals = stats["totals"]
    lines = [
        "AI Automation Usage",
        "",
        "This report tracks successful requests processed by this add-on.",
        "Estimated USD is derived from model pricing in the add-on and is not an invoice source of truth.",
        "",
        "Totals",
        f"- Requests: {totals['request_count']:,}",
        f"- Notes processed: {totals['note_count']:,}",
        f"- Input tokens: {totals['input_tokens']:,}",
        f"- Cached input tokens: {totals['cached_input_tokens']:,}",
        f"- Output tokens: {totals['output_tokens']:,}",
        f"- Reasoning tokens: {totals['reasoning_tokens']:,}",
        f"- Total tokens: {totals['total_tokens']:,}",
    ]
    if totals["estimated_cost_usd"] is not None:
        lines.append(f"- Estimated spend: ${totals['estimated_cost_usd']:.4f}")
    else:
        lines.append("- Estimated spend: unavailable")

    if stats["by_model"]:
        lines.extend(["", "By model"])
        for model_name in sorted(stats["by_model"]):
            model_totals = stats["by_model"][model_name]
            cost_text = "unavailable"
            if model_totals["estimated_cost_usd"] is not None:
                cost_text = f"${model_totals['estimated_cost_usd']:.4f}"
            lines.append(
                f"- {model_name}: {model_totals['request_count']:,} req, "
                f"{model_totals['total_tokens']:,} tokens, {cost_text}"
            )

    if stats["recent_runs"]:
        lines.extend(["", "Recent runs"])
        for run in stats["recent_runs"][:10]:
            cost_text = "cost unavailable"
            if run["estimated_cost_usd"] is not None:
                cost_text = f"${run['estimated_cost_usd']:.4f}"
            lines.append(
                f"- {run['timestamp']}: {run['model']}, "
                f"{run['request_count']} req, {run['total_tokens']:,} tokens, {cost_text}"
            )

    return "\n".join(lines)


def _default_usage_stats() -> dict[str, Any]:
    return {
        "totals": _empty_totals(),
        "by_model": {},
        "recent_runs": [],
    }


def _empty_totals() -> dict[str, Any]:
    return {
        "note_count": 0,
        "request_count": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": None,
    }


def _increment_totals(
    totals: dict[str, Any],
    *,
    note_count: int,
    request_count: int,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    total_tokens: int,
    estimated_cost_usd: float | None,
) -> None:
    totals["note_count"] += note_count
    totals["request_count"] += request_count
    totals["input_tokens"] += input_tokens
    totals["cached_input_tokens"] += cached_input_tokens
    totals["output_tokens"] += output_tokens
    totals["reasoning_tokens"] += reasoning_tokens
    totals["total_tokens"] += total_tokens
    if estimated_cost_usd is not None:
        totals["estimated_cost_usd"] = float(totals.get("estimated_cost_usd") or 0.0) + estimated_cost_usd


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    merged = _default_usage_stats()
    merged["totals"].update(data.get("totals", {}))
    by_model = data.get("by_model", {})
    if isinstance(by_model, dict):
        merged["by_model"] = {}
        for model_name, totals in by_model.items():
            if isinstance(model_name, str) and isinstance(totals, dict):
                merged["by_model"][model_name] = _empty_totals()
                merged["by_model"][model_name].update(totals)
    recent_runs = data.get("recent_runs", [])
    if isinstance(recent_runs, list):
        merged["recent_runs"] = [run for run in recent_runs if isinstance(run, dict)]
    return merged
