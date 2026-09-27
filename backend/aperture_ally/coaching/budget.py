"""Per-session spend guard for live coaching.

Counts paid (non-mock) provider calls recorded in ``model_calls``. The call cap and USD cap apply to
assessments and follow-up answers; transcription is counted in spend but never blocked, so voice
commands like "resume coaching" keep working after the cap is hit. The USD cap only sees models with a
configured price (``APERTURE_ALLY_PRICES``); unpriced calls are reported separately.
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import ModelCall, Session
from .providers.base import estimate_cost

CAPPED_PURPOSES = ("assess", "answer")


class BudgetExceeded(Exception):
    pass


def limits(session: Session, settings: Settings) -> tuple[int | None, float | None]:
    max_calls = session.max_model_calls if session.max_model_calls is not None else settings.session_max_model_calls
    budget = session.budget_usd if session.budget_usd is not None else settings.session_budget_usd
    return max_calls, budget


def usage_summary(calls: list[ModelCall], session: Session, settings: Settings) -> dict[str, Any]:
    paid = [c for c in calls if c.provider != "mock"]
    capped = [c for c in paid if c.purpose in CAPPED_PURPOSES]
    cost, unpriced = 0.0, 0
    for c in paid:
        price = settings.prices.get(c.model_resolved or "") or settings.prices.get(c.model_requested or "")
        est = estimate_cost(c.usage, price)
        if est is None:
            unpriced += 1
        else:
            cost += est
    max_calls, budget = limits(session, settings)
    reason = None
    if max_calls is not None and len(capped) >= max_calls:
        reason = f"{len(capped)} of {max_calls} paid coaching calls used"
    elif budget is not None and cost >= budget:
        reason = f"estimated spend ${cost:.2f} reached the ${budget:.2f} cap"
    return {
        "paid_calls": len(paid), "capped_calls": len(capped), "max_model_calls": max_calls,
        "estimated_cost_usd": round(cost, 4), "budget_usd": budget, "unpriced_calls": unpriced,
        "exceeded": reason is not None, "reason": reason,
        "note": ("USD cap ignores unpriced calls; set APERTURE_ALLY_PRICES" if budget is not None and unpriced else None),
    }
