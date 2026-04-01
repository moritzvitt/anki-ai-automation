from __future__ import annotations

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import QAction
from aqt.utils import showCritical, showInfo

from .billing import BillingError, fetch_billing_summary
from .config import ConfigError, load_config
from .usage_stats import build_usage_report, load_usage_stats


def register_usage_menu() -> None:
    if mw is None:
        return

    action = QAction("AI Automation Usage", mw)
    action.triggered.connect(_show_usage_report)
    mw.form.menuTools.addAction(action)


def _show_usage_report() -> None:
    if mw is None:
        return

    try:
        config = load_config()
    except ConfigError as error:
        showCritical(str(error), parent=mw)
        return

    op = QueryOp(
        parent=mw,
        op=lambda _col: _load_usage_report(config.api_key),
        success=lambda report: showInfo(report, parent=mw),
    )
    op.with_progress(label="Loading AI Automation usage...")
    op.run_in_background()


def _load_usage_report(api_key: str) -> str:
    local_report = build_usage_report(load_usage_stats())
    try:
        billing = fetch_billing_summary(api_key=api_key)
    except BillingError as error:
        return "\n".join(
            [
                "Official OpenAI Spend",
                "",
                str(error),
                "",
                local_report,
            ]
        )

    currency = (billing.currency or "usd").upper()
    return "\n".join(
        [
            "Official OpenAI Spend",
            "",
            "Fetched from OpenAI's organization Costs API.",
            f"- Today: {currency} {billing.today_cost:.4f}",
            f"- Last 7 days: {currency} {billing.last_7_days_cost:.4f}",
            f"- This month: {currency} {billing.month_to_date_cost:.4f}",
            "",
            local_report,
        ]
    )
