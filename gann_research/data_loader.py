"""
Data Loader — Load XAUUSD M1 CSVs into pandas DataFrames.

Handles the HistData.com ASCII format:
    YYYYMMDD HHMMSS;Open;High;Low;Close;Volume
"""

import os
import glob
import pandas as pd
import numpy as np
from pathlib import Path


HISTDATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "histdata"
)


def load_m1_csv(filepath: str) -> pd.DataFrame:
    """Load a single M1 CSV file.

    Handles two formats:
    - DAT_ASCII: YYYYMMDD HHMMSS;O;H;L;C;V  (semicolon, 6 fields)
    - DAT_MT:    YYYY.MM.DD,HH:MM,O,H,L,C,V  (comma, 7 fields)
    """
    fname = os.path.basename(filepath)

    if "DAT_MT_" in fname:
        # MetaTrader format: YYYY.MM.DD,HH:MM,O,H,L,C,V
        df = pd.read_csv(
            filepath,
            sep=",",
            header=None,
            names=["date_str", "time_str", "open", "high", "low", "close", "volume"],
        )
        df["time"] = pd.to_datetime(df["date_str"] + " " + df["time_str"],
                                     format="%Y.%m.%d %H:%M")
        df.drop(columns=["date_str", "time_str"], inplace=True)
    else:
        # HistData ASCII format: YYYYMMDD HHMMSS;O;H;L;C;V
        df = pd.read_csv(
            filepath,
            sep=";",
            header=None,
            names=["datetime_str", "open", "high", "low", "close", "volume"],
        )
        df["time"] = pd.to_datetime(df["datetime_str"], format="%Y%m%d %H%M%S")
        df.drop(columns=["datetime_str"], inplace=True)

    df.set_index("time", inplace=True)
    df.sort_index(inplace=True)
    return df


def load_years(
    start_year: int = 2009,
    end_year: int = 2026,
    histdata_dir: str | None = None,
) -> pd.DataFrame:
    """Load multiple years of M1 data into a single DataFrame.

    Handles both DAT_ASCII_ and DAT_MT_ file prefixes.
    """
    data_dir = histdata_dir or HISTDATA_DIR
    frames = []
    # Collect both file patterns
    for prefix in ["DAT_ASCII_XAUUSD_M1_", "DAT_MT_XAUUSD_M1_"]:
        pattern = os.path.join(data_dir, prefix + "*.csv")
        for fpath in sorted(glob.glob(pattern)):
            fname = os.path.basename(fpath)
            year_part = fname.replace(prefix, "").replace(".csv", "")
            year = int(year_part[:4])
            if year < start_year or year > end_year:
                continue
            print(f"  Loading {fname}...")
            frames.append(load_m1_csv(fpath))
    if not frames:
        raise FileNotFoundError(f"No CSV files found in {data_dir}")
    df = pd.concat(frames)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="first")]
    print(f"  Total: {len(df):,} M1 bars, {df.index[0]} to {df.index[-1]}")
    return df


def resample_timeframe(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample M1 data to higher timeframes.

    tf: 'M5', 'M15', 'H1', 'H4', 'D1', 'W1'
    """
    freq_map = {
        "M5": "5min",
        "M15": "15min",
        "H1": "1h",
        "H4": "4h",
        "D1": "1D",
        "W1": "1W",
    }
    freq = freq_map.get(tf)
    if not freq:
        raise ValueError(f"Unknown timeframe: {tf}")
    ohlcv = m1.resample(freq).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    ohlcv.dropna(subset=["open"], inplace=True)
    return ohlcv


def split_train_test(
    df: pd.DataFrame,
    train_end: str = "2019-12-31",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split data into train (2015-2019) and test (2020-2026)."""
    train = df[df.index <= train_end]
    test = df[df.index > train_end]
    print(f"  Train: {len(train):,} bars ({train.index[0]} to {train.index[-1]})")
    print(f"  Test:  {len(test):,} bars ({test.index[0]} to {test.index[-1]})")
    return train, test
