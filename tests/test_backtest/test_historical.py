"""Tests for HistoricalDataLoader -- histdata.com CSV ingestion pipeline.

Covers: CSV parsing, EST-to-UTC conversion, data validation with auto-repair,
Parquet partitioned output, and DuckDB-based bar loading.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from fxsoqqabot.backtest.config import BacktestConfig
from fxsoqqabot.backtest.historical import HistoricalDataLoader


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Histdata.com format: YYYYMMDD HHMMSS;open;high;low;close;volume
# No headers, semicolon-delimited. Timestamps are in EST (no DST).
SAMPLE_CSV_LINES = [
    "20150102 170000;1183.640;1183.950;1183.430;1183.780;97",
    "20150102 170100;1183.780;1183.900;1183.600;1183.850;45",
    "20150102 170200;1183.850;1184.100;1183.700;1184.050;62",
    "20150102 170300;1184.050;1184.200;1183.900;1184.100;38",
    "20150102 170400;1184.100;1184.300;1184.000;1184.250;51",
]


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create a basic histdata.com CSV file."""
    csv_file = tmp_path / "XAUUSD_M1_2015.csv"
    csv_file.write_text("\n".join(SAMPLE_CSV_LINES) + "\n")
    return csv_file


@pytest.fixture
def config(tmp_path: Path) -> BacktestConfig:
    """BacktestConfig pointing at tmp dirs."""
    return BacktestConfig(
        histdata_dir=str(tmp_path / "histdata"),
        parquet_dir=str(tmp_path / "historical"),
    )


@pytest.fixture
def loader(config: BacktestConfig) -> HistoricalDataLoader:
    """Loader instance with tmp config."""
    return HistoricalDataLoader(config)


# ---------------------------------------------------------------------------
# Test 1: parse_histdata_csv reads semicolon-delimited, no-header CSV
# ---------------------------------------------------------------------------
def test_parse_csv_basic_columns(loader: HistoricalDataLoader, sample_csv: Path) -> None:
    """parse_histdata_csv produces correct columns from histdata format."""
    df = loader.parse_histdata_csv(sample_csv)
    assert len(df) == 5
    # Must have these columns
    for col in ("datetime_utc", "time", "open", "high", "low", "close", "volume", "year", "month"):
        assert col in df.columns, f"Missing column: {col}"
    # Check OHLCV types
    assert df["open"].dtype == np.float64
    assert df["volume"].dtype == np.int64


# ---------------------------------------------------------------------------
# Test 2: EST to UTC conversion -- adds exactly 5 hours
# ---------------------------------------------------------------------------
def test_est_to_utc_conversion(loader: HistoricalDataLoader, sample_csv: Path) -> None:
    """EST timestamps converted to UTC by adding 5 hours per histdata.com spec."""
    df = loader.parse_histdata_csv(sample_csv)
    # First row: 2015-01-02 17:00:00 EST -> 2015-01-02 22:00:00 UTC
    first_utc = df["datetime_utc"].iloc[0]
    assert first_utc == pd.Timestamp("2015-01-02 22:00:00")
    # Unix timestamp for 2015-01-02 22:00:00 UTC = 1420236000
    expected_ts = int(pd.Timestamp("2015-01-02 22:00:00").timestamp())
    assert df["time"].iloc[0] == expected_ts


# ---------------------------------------------------------------------------
# Test 3: year and month partition columns from UTC datetime
# ---------------------------------------------------------------------------
def test_partition_columns(loader: HistoricalDataLoader, sample_csv: Path) -> None:
    """Year and month columns derived from UTC datetime for Parquet partitioning."""
    df = loader.parse_histdata_csv(sample_csv)
    assert df["year"].iloc[0] == 2015
    assert df["month"].iloc[0] == 1


# ---------------------------------------------------------------------------
# Test 4: validate removes duplicate timestamps (keep first)
# ---------------------------------------------------------------------------
def test_validate_removes_duplicates(loader: HistoricalDataLoader) -> None:
    """Duplicate timestamps are removed keeping first occurrence."""
    df = pd.DataFrame({
        "datetime_utc": pd.to_datetime(["2015-01-02 22:00:00", "2015-01-02 22:00:00", "2015-01-02 22:01:00"]),
        "time": [1420236000, 1420236000, 1420236060],
        "open": [1183.64, 9999.00, 1183.78],
        "high": [1183.95, 9999.00, 1183.90],
        "low": [1183.43, 9999.00, 1183.60],
        "close": [1183.78, 9999.00, 1183.85],
        "volume": [97, 10, 45],
        "year": [2015, 2015, 2015],
        "month": [1, 1, 1],
    })
    cleaned, report = loader.validate_bar_data(df)
    assert len(cleaned) == 2
    # First occurrence kept (open=1183.64), not the duplicate (open=9999)
    assert cleaned["open"].iloc[0] == pytest.approx(1183.64)
    assert report["duplicates_removed"] == 1


# ---------------------------------------------------------------------------
# Test 5: validate sorts non-monotonic timestamps
# ---------------------------------------------------------------------------
def test_validate_sorts_non_monotonic(loader: HistoricalDataLoader) -> None:
    """Non-monotonic timestamps are sorted into ascending order."""
    df = pd.DataFrame({
        "datetime_utc": pd.to_datetime(["2015-01-02 22:02:00", "2015-01-02 22:00:00", "2015-01-02 22:01:00"]),
        "time": [1420236120, 1420236000, 1420236060],
        "open": [1184.05, 1183.64, 1183.78],
        "high": [1184.20, 1183.95, 1183.90],
        "low": [1183.90, 1183.43, 1183.60],
        "close": [1184.10, 1183.78, 1183.85],
        "volume": [38, 97, 45],
        "year": [2015, 2015, 2015],
        "month": [1, 1, 1],
    })
    cleaned, report = loader.validate_bar_data(df)
    times = cleaned["time"].tolist()
    assert times == sorted(times)
    assert times[0] == 1420236000


# ---------------------------------------------------------------------------
# Test 6: validate flags and removes extreme range bars (>10x mean)
# ---------------------------------------------------------------------------
def test_validate_removes_extreme_bars(loader: HistoricalDataLoader) -> None:
    """Bars with range > 10x mean range are removed."""
    data = {
        "datetime_utc": pd.to_datetime([
            "2015-01-02 22:00:00", "2015-01-02 22:01:00",
            "2015-01-02 22:02:00", "2015-01-02 22:03:00",
            "2015-01-02 22:04:00",
        ]),
        "time": [1420236000 + i * 60 for i in range(5)],
        "open": [1183.64, 1183.78, 1183.85, 1184.05, 1184.10],
        "high": [1183.95, 1183.90, 1184.10, 1184.20, 1184.30],
        "low": [1183.43, 1183.60, 1183.70, 1183.90, 1184.00],
        "close": [1183.78, 1183.85, 1184.05, 1184.10, 1184.25],
        "volume": [97, 45, 62, 38, 51],
        "year": [2015] * 5,
        "month": [1] * 5,
    }
    # Normal ranges are ~0.3-0.5. Make bar index 2 extreme: range = 50 (>> 10x mean)
    data["high"][2] = 1233.85  # range = 1233.85 - 1183.70 = 50.15
    df = pd.DataFrame(data)
    cleaned, report = loader.validate_bar_data(df)
    assert report["extreme_bars_removed"] >= 1
    assert len(cleaned) < len(df)


# ---------------------------------------------------------------------------
# Test 7: validate counts zero-volume bars but does NOT remove them
# ---------------------------------------------------------------------------
def test_validate_counts_zero_volume_no_remove(loader: HistoricalDataLoader) -> None:
    """Zero-volume bars are counted in report but not removed."""
    df = pd.DataFrame({
        "datetime_utc": pd.to_datetime([
            "2015-01-02 22:00:00", "2015-01-02 22:01:00", "2015-01-02 22:02:00",
        ]),
        "time": [1420236000, 1420236060, 1420236120],
        "open": [1183.64, 1183.78, 1183.85],
        "high": [1183.95, 1183.90, 1184.10],
        "low": [1183.43, 1183.60, 1183.70],
        "close": [1183.78, 1183.85, 1184.05],
        "volume": [97, 0, 62],
        "year": [2015, 2015, 2015],
        "month": [1, 1, 1],
    })
    cleaned, report = loader.validate_bar_data(df)
    assert len(cleaned) == 3  # NOT removed
    assert report["zero_volume_bars"] == 1


# ---------------------------------------------------------------------------
# Test 8: validate interpolates small gaps (<=5 bars) via forward-fill
# ---------------------------------------------------------------------------
def test_validate_interpolates_small_gaps(loader: HistoricalDataLoader) -> None:
    """Small gaps (<=5 missing bars) are filled via forward-fill."""
    # Two bars with a 3-minute gap between them (missing 2 bars)
    df = pd.DataFrame({
        "datetime_utc": pd.to_datetime(["2015-01-02 22:00:00", "2015-01-02 22:03:00"]),
        "time": [1420236000, 1420236180],
        "open": [1183.64, 1184.05],
        "high": [1183.95, 1184.20],
        "low": [1183.43, 1183.90],
        "close": [1183.78, 1184.10],
        "volume": [97, 38],
        "year": [2015, 2015],
        "month": [1, 1],
    })
    cleaned, report = loader.validate_bar_data(df)
    # Should have 4 bars: original 2 + 2 interpolated
    assert len(cleaned) == 4
    assert report["gaps_interpolated"] >= 2
    # Interpolated bars have volume=0
    interpolated = cleaned[cleaned["volume"] == 0]
    assert len(interpolated) == 2


# ---------------------------------------------------------------------------
# Test 9: validate reports large gaps (>5 bars) without filling
# ---------------------------------------------------------------------------
def test_validate_reports_large_gaps(loader: HistoricalDataLoader) -> None:
    """Large gaps (>5 missing bars) are reported but NOT filled."""
    # Two bars with a 10-minute gap (missing 9 bars -- large gap)
    df = pd.DataFrame({
        "datetime_utc": pd.to_datetime(["2015-01-02 22:00:00", "2015-01-02 22:10:00"]),
        "time": [1420236000, 1420236600],
        "open": [1183.64, 1184.05],
        "high": [1183.95, 1184.20],
        "low": [1183.43, 1183.90],
        "close": [1183.78, 1184.10],
        "volume": [97, 38],
        "year": [2015, 2015],
        "month": [1, 1],
    })
    cleaned, report = loader.validate_bar_data(df)
    # Should NOT fill -- stays at 2 bars
    assert len(cleaned) == 2
    assert report["large_gaps"] >= 1


# ---------------------------------------------------------------------------
# Test 10: convert_to_parquet writes partitioned Parquet readable by DuckDB
# ---------------------------------------------------------------------------
def test_convert_to_parquet(loader: HistoricalDataLoader, sample_csv: Path, tmp_path: Path) -> None:
    """Parquet written with year/month partitioning and readable by DuckDB."""
    df = loader.parse_histdata_csv(sample_csv)
    cleaned, _ = loader.validate_bar_data(df)
    output_dir = tmp_path / "parquet_out"
    result_path = loader.convert_to_parquet(cleaned, output_dir)
    assert result_path.exists()

    # Verify DuckDB can read it
    con = duckdb.connect()
    result = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{result_path.as_posix()}/**/*.parquet')"
    ).fetchone()
    assert result[0] == len(cleaned)
    con.close()


# ---------------------------------------------------------------------------
# Test 11: load_bars returns correct columns for time range query
# ---------------------------------------------------------------------------
def test_load_bars_time_range(loader: HistoricalDataLoader, sample_csv: Path, tmp_path: Path, config: BacktestConfig) -> None:
    """load_bars returns DataFrame with correct columns for time range."""
    df = loader.parse_histdata_csv(sample_csv)
    cleaned, _ = loader.validate_bar_data(df)
    output_dir = Path(config.parquet_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    loader.convert_to_parquet(cleaned, output_dir)

    # Query the full range
    start_time = int(cleaned["time"].min())
    end_time = int(cleaned["time"].max()) + 1  # end-exclusive
    result = loader.load_bars(start_time, end_time)

    assert len(result) > 0
    for col in ("time", "open", "high", "low", "close", "volume"):
        assert col in result.columns, f"Missing column: {col}"
    # Verify time range
    assert result["time"].min() >= start_time
    assert result["time"].max() < end_time


# ---------------------------------------------------------------------------
# Test 12: Quality report has required keys
# ---------------------------------------------------------------------------
def test_quality_report_keys(loader: HistoricalDataLoader, sample_csv: Path) -> None:
    """Quality report dict contains all required keys."""
    df = loader.parse_histdata_csv(sample_csv)
    _, report = loader.validate_bar_data(df)
    required_keys = {
        "original_rows", "final_rows", "issues", "date_range",
        "duplicates_removed", "gaps_interpolated", "extreme_bars_removed",
        "zero_volume_bars", "large_gaps",
    }
    assert required_keys.issubset(set(report.keys()))
    assert isinstance(report["issues"], list)
    assert isinstance(report["date_range"], tuple)
    assert len(report["date_range"]) == 2
