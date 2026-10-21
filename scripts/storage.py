"""
PIT (Point-In-Time) correct storage layer for Finance-NEWS.

Three layers:
  - raw/        : original JSON per source per day
  - processed/  : cleaned, dedup'd, structured Parquet with 3 timestamps
  - factors/    : per-day per-symbol factor values (Parquet)

Every processed record carries 3 timestamps to prevent look-ahead bias:
  - publish_ts    : when the news was officially published
  - ingestion_ts  : when WE actually fetched/ingested it
  - actionable_ts : earliest moment the news could legitimately be used for a
                    decision (open or close after publish, weekend-aware)

Backtests MUST filter by actionable_ts, never by publish_ts.
"""

from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import duckdb  # type: ignore
except Exception:  # pragma: no cover
    duckdb = None


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
FACTORS = DATA / "factors"

for p in (RAW, PROCESSED, FACTORS):
    p.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# PIT timestamp rules
# --------------------------------------------------------------------------- #

MARKET_OPEN = time(9, 0)
MARKET_CLOSE = time(13, 30)

HOLIDAY_FILE = DATA / "calendar" / "tw_holidays.json"
_HOLIDAYS: set[str] | None = None


def _tw_holidays() -> set[str]:
    """Load TW market closure dates (YYYY-MM-DD) once; empty set if file missing."""
    global _HOLIDAYS
    if _HOLIDAYS is None:
        _HOLIDAYS = set()
        if HOLIDAY_FILE.exists():
            raw = json.loads(HOLIDAY_FILE.read_text(encoding="utf-8"))
            for key, dates in raw.items():
                if not key.startswith("_") and isinstance(dates, list):
                    _HOLIDAYS.update(dates)
    return _HOLIDAYS


def _is_closed(d: datetime) -> bool:
    """True on weekends and TW market holidays (data/calendar/tw_holidays.json)."""
    return d.weekday() >= 5 or d.strftime("%Y-%m-%d") in _tw_holidays()


def _next_trading_day(d: datetime) -> datetime:
    """Advance d.date() to the next trading day. Time component preserved."""
    nd = d + timedelta(days=1)
    while _is_closed(nd):
        nd += timedelta(days=1)
    return nd


def _to_trading_day(d: datetime) -> datetime:
    """If d falls on a closed day, push forward to next trading day at 09:00."""
    while _is_closed(d):
        d = (d + timedelta(days=1)).replace(
            hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
        )
    return d


def compute_actionable_ts(publish_ts: datetime) -> datetime:
    """
    Map publish time -> earliest actionable time (TW market hours, closed-day-aware).

    Rules:
      - published before 09:00 on a trading day -> same day 09:00 (open)
      - published 09:00 <= t < 13:30            -> same day 13:30 (close)
      - published >= 13:30                      -> next trading day 09:00
      - published on weekend / market holiday   -> next trading day 09:00

    Holidays come from data/calendar/tw_holidays.json (maintained yearly).
    """
    if publish_ts is None or pd.isna(publish_ts):
        return publish_ts  # type: ignore[return-value]

    if isinstance(publish_ts, pd.Timestamp):
        publish_ts = publish_ts.to_pydatetime()

    # Closed-day publish (weekend or holiday) -> next trading day's open.
    if _is_closed(publish_ts):
        candidate = publish_ts.replace(
            hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
        )
        return _to_trading_day(candidate)

    t = publish_ts.time()
    base = publish_ts.replace(second=0, microsecond=0)

    if t < MARKET_OPEN:
        return base.replace(hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute)
    if t < MARKET_CLOSE:
        return base.replace(hour=MARKET_CLOSE.hour, minute=MARKET_CLOSE.minute)

    # After close -> next trading day's open
    nxt = _next_trading_day(publish_ts).replace(
        hour=MARKET_OPEN.hour, minute=MARKET_OPEN.minute, second=0, microsecond=0
    )
    return nxt


# --------------------------------------------------------------------------- #
# Raw layer (JSON per source per day)
# --------------------------------------------------------------------------- #

def save_raw(source: str, date: str, items: list[dict]) -> Path:
    """Persist raw fetched items as JSON. Overwrites existing file."""
    out_dir = RAW / source
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{date}.json"
    out.write_text(
        json.dumps(items, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out


def load_raw(source: str, date: str) -> list[dict]:
    """Load raw JSON for one source on one day; returns [] if missing."""
    path = RAW / source / f"{date}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Processed layer (Parquet, partitioned by date)
# --------------------------------------------------------------------------- #

PROCESSED_REQUIRED = [
    "id",
    "source",
    "title",
    "url",
    "publish_ts",
    "ingestion_ts",
    "actionable_ts",
]


def _processed_path(date: str) -> Path:
    return PROCESSED / f"date={date}" / "data.parquet"


def save_processed(date: str, df: pd.DataFrame) -> Path:
    """Validate and save a processed-day Parquet partition."""
    validate_schema(df, "processed")
    out = _processed_path(date)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", index=False)
    return out


def load_processed(start: str, end: str) -> pd.DataFrame:
    """Load processed parquet partitions between [start, end] inclusive."""
    s = pd.to_datetime(start).date()
    e = pd.to_datetime(end).date()
    frames: list[pd.DataFrame] = []
    for part in sorted(PROCESSED.glob("date=*/data.parquet")):
        d = pd.to_datetime(part.parent.name.split("=", 1)[1]).date()
        if s <= d <= e:
            frames.append(pd.read_parquet(part))
    if not frames:
        return pd.DataFrame(columns=PROCESSED_REQUIRED)
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Factor layer
# --------------------------------------------------------------------------- #

FACTOR_REQUIRED = ["symbol", "date", "value", "actionable_ts"]


def _factor_path(name: str, date: str) -> Path:
    return FACTORS / name / f"date={date}" / "data.parquet"


def save_factor(name: str, date: str, df: pd.DataFrame) -> Path:
    validate_schema(df, "factor")
    out = _factor_path(name, date)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", index=False)
    return out


def load_factor(name: str, start: str, end: str) -> pd.DataFrame:
    s = pd.to_datetime(start).date()
    e = pd.to_datetime(end).date()
    base = FACTORS / name
    frames: list[pd.DataFrame] = []
    if not base.exists():
        return pd.DataFrame(columns=FACTOR_REQUIRED)
    for part in sorted(base.glob("date=*/data.parquet")):
        d = pd.to_datetime(part.parent.name.split("=", 1)[1]).date()
        if s <= d <= e:
            frames.append(pd.read_parquet(part))
    if not frames:
        return pd.DataFrame(columns=FACTOR_REQUIRED)
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# DuckDB query helper
# --------------------------------------------------------------------------- #

def query(sql: str) -> pd.DataFrame:
    """Run an ad-hoc SQL query against the parquet datasets via DuckDB."""
    if duckdb is None:
        raise RuntimeError("duckdb not installed; `pip install duckdb`")
    con = duckdb.connect()
    try:
        # cwd-relative globs in SQL should resolve from project root
        con.execute(f"SET file_search_path='{ROOT.as_posix()}'")
        return con.execute(sql).df()
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# as-of merge (look-ahead-safe)
# --------------------------------------------------------------------------- #

def asof_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    left_time: str,
    right_time: str,
    by: str,
) -> pd.DataFrame:
    """
    Backward as-of merge: for each row in `left`, attach the most recent row
    in `right` whose timestamp is <= the left timestamp. Prevents look-ahead.
    """
    l = left.sort_values(left_time).copy()
    r = right.sort_values(right_time).copy()
    l[left_time] = pd.to_datetime(l[left_time])
    r[right_time] = pd.to_datetime(r[right_time])
    return pd.merge_asof(
        l, r,
        left_on=left_time, right_on=right_time,
        by=by, direction="backward", allow_exact_matches=True,
    )


# --------------------------------------------------------------------------- #
# Schema validation
# --------------------------------------------------------------------------- #

def _required_columns(schema_name: str) -> list[str]:
    if schema_name == "processed":
        return PROCESSED_REQUIRED
    if schema_name == "factor":
        return FACTOR_REQUIRED
    raise ValueError(f"unknown schema: {schema_name}")


def validate_schema(df: pd.DataFrame, schema_name: str) -> None:
    """Raise ValueError on missing cols or PIT-rule violations."""
    required = _required_columns(schema_name)
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{schema_name} schema missing columns: {missing}")

    if schema_name == "processed":
        pub = pd.to_datetime(df["publish_ts"])
        ing = pd.to_datetime(df["ingestion_ts"])
        act = pd.to_datetime(df["actionable_ts"])

        # ingestion must not precede publish
        bad_ingest = (ing < pub) & pub.notna() & ing.notna()
        if bad_ingest.any():
            raise ValueError(
                f"PIT violation: ingestion_ts < publish_ts in {bad_ingest.sum()} rows"
            )

        # actionable must not precede publish
        bad_act = (act < pub) & pub.notna() & act.notna()
        if bad_act.any():
            raise ValueError(
                f"PIT violation: actionable_ts < publish_ts in {bad_act.sum()} rows"
            )

        # spot-check: recomputed actionable matches stored value
        recomputed = pub.apply(lambda x: compute_actionable_ts(x) if pd.notna(x) else x)
        recomputed = pd.to_datetime(recomputed)
        mismatch = (recomputed != act) & pub.notna()
        if mismatch.any():
            raise ValueError(
                f"PIT violation: actionable_ts mismatch on {mismatch.sum()} rows; "
                "did you forget to call compute_actionable_ts()?"
            )
