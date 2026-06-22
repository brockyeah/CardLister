"""Per-user API usage report, for splitting shared Anthropic costs.

Aggregates usage_events for the current calendar month, prices the tokens by
model, and returns a per-user breakdown. Settlement happens offline — this just
tells the owner who owes what.
"""
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..database import get_db
from ..models import UsageEvent
from ..schemas import UsageReport, UsageRow

router = APIRouter(dependencies=[Depends(require_auth)])

# USD per 1M tokens, (input, output). Output includes thinking tokens.
MODEL_PRICES = {
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# Unknown/overridden models price at Opus rates so estimates never undercount.
_DEFAULT_PRICE = (5.0, 25.0)


def _cost(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = MODEL_PRICES.get(model, _DEFAULT_PRICE)
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


@router.get("", response_model=UsageReport)
def usage_report(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Group by (user, model) so each model's tokens are priced at its own rate,
    # then fold into per-user totals.
    grouped = (
        db.query(
            UsageEvent.username,
            UsageEvent.model,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
        )
        .filter(UsageEvent.created_at >= since)
        .group_by(UsageEvent.username, UsageEvent.model)
        .all()
    )

    per_user = defaultdict(lambda: {"scans": 0, "input": 0, "output": 0, "cost": 0.0})
    for username, model, scans, in_tok, out_tok in grouped:
        u = per_user[username]
        u["scans"] += scans
        u["input"] += in_tok
        u["output"] += out_tok
        u["cost"] += _cost(model, in_tok, out_tok)

    rows = [
        UsageRow(
            username=username,
            scans=u["scans"],
            input_tokens=u["input"],
            output_tokens=u["output"],
            est_cost_usd=round(u["cost"], 2),
        )
        for username, u in sorted(per_user.items(), key=lambda kv: kv[1]["cost"], reverse=True)
    ]

    return UsageReport(
        period=now.strftime("%Y-%m"),
        since=since,
        rows=rows,
        total_cost_usd=round(sum(r.est_cost_usd for r in rows), 2),
    )
