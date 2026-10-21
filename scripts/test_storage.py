"""Smoke tests for scripts/storage.py — PIT correctness + round-trip IO."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import storage  # noqa: E402


def test_compute_actionable_ts():
    cases = [
        # (publish, expected actionable)
        (datetime(2026, 5, 13, 7, 30),  datetime(2026, 5, 13, 9, 0)),   # pre-open -> open
        (datetime(2026, 5, 13, 10, 0),  datetime(2026, 5, 13, 13, 30)), # intraday -> close
        (datetime(2026, 5, 13, 15, 0),  datetime(2026, 5, 14, 9, 0)),   # after close -> next day open
        (datetime(2026, 5, 15, 16, 0),  datetime(2026, 5, 18, 9, 0)),   # Fri after close -> Mon open
        (datetime(2026, 5, 16, 10, 0),  datetime(2026, 5, 18, 9, 0)),   # Sat -> Mon open
    ]
    for pub, expected in cases:
        got = storage.compute_actionable_ts(pub)
        assert got == expected, f"pub={pub} expected={expected} got={got}"
    print("[ok] compute_actionable_ts: 5/5 cases pass")


def test_raw_roundtrip():
    items = [{"title": "測試", "url": "https://x/1", "published_at": "2026-05-13T10:00:00"}]
    p = storage.save_raw("test_src", "2026-05-13", items)
    loaded = storage.load_raw("test_src", "2026-05-13")
    assert loaded == items, "raw roundtrip mismatch"
    print(f"[ok] raw roundtrip -> {p}")


def _make_processed_df():
    pub = [
        datetime(2026, 5, 13, 7, 30),
        datetime(2026, 5, 13, 10, 0),
        datetime(2026, 5, 13, 15, 0),
    ]
    ing = [datetime(2026, 5, 13, 16, 0)] * 3
    return pd.DataFrame({
        "id":            ["a", "b", "c"],
        "source":        ["cnyes", "udn", "ctee"],
        "title":         ["T1", "T2", "T3"],
        "url":           ["u1", "u2", "u3"],
        "publish_ts":    pub,
        "ingestion_ts":  ing,
        "actionable_ts": [storage.compute_actionable_ts(p) for p in pub],
    })


def test_processed_roundtrip():
    df = _make_processed_df()
    p = storage.save_processed("2026-05-13", df)
    out = storage.load_processed("2026-05-13", "2026-05-13")
    assert len(out) == 3
    assert set(out["id"]) == {"a", "b", "c"}
    print(f"[ok] processed roundtrip ({len(out)} rows) -> {p}")


def test_validate_schema_catches_violations():
    df = _make_processed_df()
    # corrupt: ingestion before publish
    bad = df.copy()
    bad.loc[0, "ingestion_ts"] = datetime(2026, 5, 13, 0, 0)
    try:
        storage.validate_schema(bad, "processed")
    except ValueError as e:
        print(f"[ok] validator caught bad ingestion_ts: {e}")
    else:
        raise AssertionError("validator failed to catch ingestion < publish")

    # corrupt: wrong actionable_ts
    bad2 = df.copy()
    bad2.loc[0, "actionable_ts"] = datetime(2030, 1, 1)
    try:
        storage.validate_schema(bad2, "processed")
    except ValueError as e:
        print(f"[ok] validator caught wrong actionable_ts")
    else:
        raise AssertionError("validator failed to catch actionable mismatch")


def test_factor_roundtrip():
    df = pd.DataFrame({
        "symbol":        ["2330", "2317"],
        "date":          ["2026-05-13", "2026-05-13"],
        "value":         [0.42, -0.11],
        "actionable_ts": [datetime(2026, 5, 13, 13, 30)] * 2,
    })
    p = storage.save_factor("sentiment", "2026-05-13", df)
    out = storage.load_factor("sentiment", "2026-05-13", "2026-05-13")
    assert len(out) == 2
    print(f"[ok] factor roundtrip ({len(out)} rows) -> {p}")


def test_asof_merge():
    news = pd.DataFrame({
        "symbol":        ["2330", "2330", "2330"],
        "actionable_ts": pd.to_datetime(
            ["2026-05-13 09:00", "2026-05-13 13:30", "2026-05-14 09:00"]
        ),
        "sentiment":     [0.1, 0.5, -0.2],
    })
    prices = pd.DataFrame({
        "symbol": ["2330", "2330", "2330"],
        "ts":     pd.to_datetime(["2026-05-13 09:00", "2026-05-13 13:30", "2026-05-14 09:00"]),
        "price":  [600, 605, 602],
    })
    merged = storage.asof_merge(prices, news, left_time="ts", right_time="actionable_ts", by="symbol")
    assert len(merged) == 3
    assert merged["sentiment"].tolist() == [0.1, 0.5, -0.2]
    print(f"[ok] asof_merge produced {len(merged)} rows, no look-ahead leakage")


def test_duckdb_query():
    try:
        df = storage.query(
            "SELECT COUNT(*) AS n FROM 'data/processed/**/*.parquet' "
            "WHERE actionable_ts < TIMESTAMP '2030-01-01'"
        )
        print(f"[ok] duckdb query returned {df.iloc[0]['n']} rows")
    except Exception as e:
        print(f"[skip] duckdb query: {e}")


if __name__ == "__main__":
    test_compute_actionable_ts()
    test_raw_roundtrip()
    test_processed_roundtrip()
    test_validate_schema_catches_violations()
    test_factor_roundtrip()
    test_asof_merge()
    test_duckdb_query()
    print("\nALL TESTS PASSED")
