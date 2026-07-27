from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

PERIOD_DELTAS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


@dataclass(frozen=True)
class ReportPeriod:
    start: datetime
    end: datetime
    label: str

    def as_dict(self):
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
        }


def resolve_period(
    *,
    period: str = "7d",
    start_date=None,
    end_date=None,
    now=None,
) -> ReportPeriod:
    """Resolve a preset or inclusive date range to an exclusive UTC window."""
    if bool(start_date) != bool(end_date):
        raise ValueError("start-date and end-date must be provided together")

    if start_date and end_date:
        if start_date > end_date:
            raise ValueError("start-date must be before or equal to end-date")
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        return ReportPeriod(start=start, end=end, label="custom")

    if period not in PERIOD_DELTAS:
        raise ValueError(f"Unsupported period: {period}")

    end = now or datetime.now(UTC)
    return ReportPeriod(start=end - PERIOD_DELTAS[period], end=end, label=period)
