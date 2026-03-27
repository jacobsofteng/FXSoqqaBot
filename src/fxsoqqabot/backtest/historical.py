"""HistoricalDataLoader: histdata.com CSV ingestion pipeline (DATA-04).

Converts histdata.com M1 bar CSV files into validated, UTC-timestamped
Parquet files partitioned by year/month. Provides DuckDB-based bar loading
for backtesting queries.

Data format (histdata.com):
- Semicolon-delimited, no headers
- Columns: datetime_str;open;high;low;close;volume
- Datetime format: YYYYMMDD HHMMSS in EST (no DST adjustment)
- EST to UTC: add exactly 5 hours per histdata.com specification

Validation per D-03:
- Duplicate timestamps: removed (keep first)
- Non-monotonic: sorted ascending
- Small gaps (<=5 bars): interpolated via forward-fill
- Large gaps (>5 bars): reported, not filled (weekends/holidays)
- Extreme range bars (>10x mean): removed
- Zero-volume bars: counted but kept (low liquidity is normal)
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import structlog

from fxsoqqabot.backtest.config import BacktestConfig


class HistoricalDataLoader:
    """Ingests histdata.com CSVs, validates, writes Parquet, loads via DuckDB.

    Methods:
        parse_histdata_csv: Read semicolon-delimited CSV, convert EST to UTC
        validate_bar_data: Clean and validate bar data with quality report
        convert_to_parquet: Write partitioned Parquet via DuckDB
        ingest_all: Full pipeline: glob CSVs -> parse -> validate -> Parquet
        load_bars: Query bars by time range from Parquet via DuckDB
        get_time_range: Get min/max timestamps from Parquet
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config
        self._logger = structlog.get_logger().bind(component="historical_data")
        self._db = duckdb.connect()  # In-memory for queries

    def parse_histdata_csv(self, filepath: Path) -> pd.DataFrame:
        """Parse a histdata.com semicolon-delimited CSV file.

        Reads CSV with no headers, semicolon delimiter, columns:
        datetime_str;open;high;low;close;volume

        Converts EST timestamps to UTC by adding 5 hours (no DST per
        histdata.com specification).

        Args:
            filepath: Path to the histdata.com CSV file.

        Returns:
            DataFrame with columns: datetime_utc, time, open, high, low,
            close, volume, year, month
        """
        df = pd.read_csv(
            filepath,
            sep=";",
            header=None,
            names=["datetime_str", "open", "high", "low", "close", "volume"],
            dtype={
                "open": np.float64,
                "high": np.float64,
                "low": np.float64,
                "close": np.float64,
                "volume": np.int64,
            },
        )

        # Parse EST datetime
        datetime_est = pd.to_datetime(df["datetime_str"], format="%Y%m%d %H%M%S")

        # Convert EST to UTC: add exactly 5 hours (no DST per histdata.com spec)
        df["datetime_utc"] = datetime_est + timedelta(hours=5)

        # Unix timestamp in seconds from UTC datetime
        df["time"] = (
            df["datetime_utc"].astype("int64") // 10**9
        ).astype(np.int64)

        # Partition columns from UTC datetime
        df["year"] = df["datetime_utc"].dt.year.astype(np.int32)
        df["month"] = df["datetime_utc"].dt.month.astype(np.int32)

        # Drop intermediate column
        df = df.drop(columns=["datetime_str"])

        self._logger.info(
            "csv_parsed",
            filepath=str(filepath),
            rows=len(df),
            date_range=(
                str(df["datetime_utc"].min()),
                str(df["datetime_utc"].max()),
            ),
        )

        return df

    def validate_bar_data(
        self, df: pd.DataFrame
    ) -> tuple[pd.DataFrame, dict]:
        """Validate and clean bar data with auto-repair per D-03.

        Validation steps:
        1. Remove duplicate timestamps (keep first)
        2. Sort non-monotonic timestamps ascending
        3. Interpolate small gaps (<=5 bars) via forward-fill
        4. Report large gaps (>5 bars) without filling
        5. Remove extreme range bars (>10x mean range)
        6. Count zero-volume bars (report only, no removal)

        Args:
            df: DataFrame from parse_histdata_csv.

        Returns:
            Tuple of (cleaned_df, quality_report dict).
        """
        original_rows = len(df)
        issues: list[str] = []
        duplicates_removed = 0
        gaps_interpolated = 0
        extreme_bars_removed = 0
        zero_volume_bars = 0
        large_gaps = 0

        cleaned = df.copy()

        # 1. Remove duplicate timestamps (keep first)
        dup_mask = cleaned["time"].duplicated(keep="first")
        duplicates_removed = int(dup_mask.sum())
        if duplicates_removed > 0:
            cleaned = cleaned[~dup_mask].reset_index(drop=True)
            issues.append(
                f"Removed {duplicates_removed} duplicate timestamps"
            )

        # 2. Sort by time if not monotonic
        if not cleaned["time"].is_monotonic_increasing:
            cleaned = cleaned.sort_values("time").reset_index(drop=True)
            issues.append("Sorted non-monotonic timestamps")

        # 3. Detect and handle gaps
        if len(cleaned) >= 2:
            expected_interval = 60  # M1 = 60 seconds
            time_diffs = np.diff(cleaned["time"].values)

            # Walk through gaps from end to start to avoid index shifts
            gap_indices = np.where(time_diffs > expected_interval)[0]

            fill_rows: list[dict] = []
            for idx in gap_indices:
                gap_bars = int(time_diffs[idx] / expected_interval) - 1
                if gap_bars <= 0:
                    continue

                if gap_bars <= 5:
                    # Small gap: interpolate via forward-fill
                    prev_row = cleaned.iloc[idx]
                    for j in range(1, gap_bars + 1):
                        new_time = int(prev_row["time"]) + j * expected_interval
                        new_dt = prev_row["datetime_utc"] + timedelta(
                            seconds=j * expected_interval
                        )
                        fill_rows.append(
                            {
                                "datetime_utc": new_dt,
                                "time": new_time,
                                "open": prev_row["close"],
                                "high": prev_row["close"],
                                "low": prev_row["close"],
                                "close": prev_row["close"],
                                "volume": 0,
                                "year": int(new_dt.year),
                                "month": int(new_dt.month),
                            }
                        )
                    gaps_interpolated += gap_bars
                else:
                    # Large gap: report only
                    large_gaps += 1
                    issues.append(
                        f"Large gap of {gap_bars} bars at time={cleaned.iloc[idx]['time']}"
                    )

            if fill_rows:
                fill_df = pd.DataFrame(fill_rows)
                # Ensure matching dtypes
                fill_df["time"] = fill_df["time"].astype(np.int64)
                fill_df["volume"] = fill_df["volume"].astype(np.int64)
                fill_df["year"] = fill_df["year"].astype(np.int32)
                fill_df["month"] = fill_df["month"].astype(np.int32)
                fill_df["open"] = fill_df["open"].astype(np.float64)
                fill_df["high"] = fill_df["high"].astype(np.float64)
                fill_df["low"] = fill_df["low"].astype(np.float64)
                fill_df["close"] = fill_df["close"].astype(np.float64)
                cleaned = (
                    pd.concat([cleaned, fill_df], ignore_index=True)
                    .sort_values("time")
                    .reset_index(drop=True)
                )
                issues.append(
                    f"Interpolated {gaps_interpolated} bars in small gaps"
                )

        # 4. Filter extreme range bars (>10x median range)
        # Use median instead of mean to avoid outlier inflation
        bar_range = cleaned["high"] - cleaned["low"]
        median_range = bar_range.median()
        if median_range > 0:
            extreme_mask = bar_range > median_range * 10
            extreme_bars_removed = int(extreme_mask.sum())
            if extreme_bars_removed > 0:
                cleaned = cleaned[~extreme_mask].reset_index(drop=True)
                issues.append(
                    f"Removed {extreme_bars_removed} extreme range bars "
                    f"(>{median_range * 10:.2f})"
                )

        # 5. Count zero-volume bars (do NOT remove)
        zero_volume_bars = int((cleaned["volume"] == 0).sum())
        if zero_volume_bars > 0:
            issues.append(
                f"Found {zero_volume_bars} zero-volume bars (kept)"
            )

        # Build quality report
        date_range = (
            cleaned["datetime_utc"].min(),
            cleaned["datetime_utc"].max(),
        ) if len(cleaned) > 0 else (None, None)

        quality_report = {
            "original_rows": original_rows,
            "final_rows": len(cleaned),
            "issues": issues,
            "date_range": date_range,
            "duplicates_removed": duplicates_removed,
            "gaps_interpolated": gaps_interpolated,
            "extreme_bars_removed": extreme_bars_removed,
            "zero_volume_bars": zero_volume_bars,
            "large_gaps": large_gaps,
        }

        self._logger.info(
            "data_validated",
            original_rows=original_rows,
            final_rows=len(cleaned),
            issues_count=len(issues),
        )

        return cleaned, quality_report

    def convert_to_parquet(
        self, df: pd.DataFrame, output_dir: Path | None = None
    ) -> Path:
        """Write DataFrame to Parquet with year/month partitioning via DuckDB.

        Args:
            df: Validated DataFrame from validate_bar_data.
            output_dir: Output directory. Defaults to config.parquet_dir.

        Returns:
            Path to the output directory containing Parquet files.
        """
        if output_dir is None:
            output_dir = Path(self._config.parquet_dir)
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Register DataFrame and use DuckDB COPY with PARTITION_BY
        con = duckdb.connect()
        con.register("bar_data", df)
        out_posix = output_dir.as_posix()
        con.execute(f"""
            COPY (
                SELECT datetime_utc, time, open, high, low, close, volume,
                       year, month
                FROM bar_data
            )
            TO '{out_posix}'
            (FORMAT PARQUET, PARTITION_BY (year, month), OVERWRITE_OR_IGNORE true)
        """)
        con.close()

        self._logger.info(
            "parquet_written",
            output_dir=str(output_dir),
            rows=len(df),
        )

        return output_dir

    def ingest_all(self, csv_dir: Path | None = None) -> dict:
        """Full ingestion pipeline: glob CSVs -> parse -> validate -> Parquet.

        Args:
            csv_dir: Directory containing CSV files. Defaults to config.histdata_dir.

        Returns:
            Combined quality report dict.
        """
        if csv_dir is None:
            csv_dir = Path(self._config.histdata_dir)
        csv_dir = Path(csv_dir)

        csv_files = sorted(csv_dir.glob("*.csv"))
        if not csv_files:
            self._logger.warning("no_csv_files_found", dir=str(csv_dir))
            return {
                "original_rows": 0,
                "final_rows": 0,
                "issues": ["No CSV files found"],
                "date_range": (None, None),
                "duplicates_removed": 0,
                "gaps_interpolated": 0,
                "extreme_bars_removed": 0,
                "zero_volume_bars": 0,
                "large_gaps": 0,
                "files_processed": 0,
            }

        all_dfs: list[pd.DataFrame] = []
        for csv_file in csv_files:
            df = self.parse_histdata_csv(csv_file)
            all_dfs.append(df)

        # Combine all parsed data
        combined = pd.concat(all_dfs, ignore_index=True)

        # Validate the combined dataset
        cleaned, report = self.validate_bar_data(combined)

        # Write to Parquet
        self.convert_to_parquet(cleaned)

        report["files_processed"] = len(csv_files)

        self._logger.info(
            "ingestion_complete",
            files=len(csv_files),
            total_rows=report["final_rows"],
        )

        return report

    def load_bars(self, start_time: int, end_time: int) -> pd.DataFrame:
        """Query bars by time range from Parquet via DuckDB.

        Uses start-inclusive, end-exclusive window boundaries per Phase 1
        convention.

        Args:
            start_time: Start Unix timestamp (inclusive).
            end_time: End Unix timestamp (exclusive).

        Returns:
            DataFrame with columns: time, open, high, low, close, volume
        """
        parquet_path = Path(self._config.parquet_dir)
        glob_pattern = f"{parquet_path.as_posix()}/**/*.parquet"

        result = self._db.execute(
            f"""
            SELECT time, open, high, low, close, volume
            FROM read_parquet('{glob_pattern}')
            WHERE time >= {start_time} AND time < {end_time}
            ORDER BY time
            """
        ).fetchdf()

        return result

    def get_time_range(self) -> tuple[int, int]:
        """Get min/max timestamps from Parquet data.

        Returns:
            Tuple of (min_time, max_time) Unix timestamps.
        """
        parquet_path = Path(self._config.parquet_dir)
        glob_pattern = f"{parquet_path.as_posix()}/**/*.parquet"

        result = self._db.execute(
            f"""
            SELECT MIN(time) as min_time, MAX(time) as max_time
            FROM read_parquet('{glob_pattern}')
            """
        ).fetchone()

        return (int(result[0]), int(result[1]))
