"""
Quick test: Compare angle direction vs fade direction on 2020-2022 data.

Loads from cleaned parquet, runs both modes, shows comparison.
"""
import sys
import os
import pandas as pd
import numpy as np

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from gann_research.data_loader import resample_timeframe
from gann_research.scalp_sim import run_scalp_simulation
from gann_research.calibrate import calibrate_angle_scales
from gann_research.swing_detector import detect_swings


def load_clean_data(start="2020-01-01", end="2022-12-31"):
    """Load cleaned parquet data for the test period."""
    parquet_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "clean", "XAUUSD_M1_clean.parquet"
    )
    print(f"Loading {parquet_path}...")
    m1 = pd.read_parquet(parquet_path)
    m1 = m1.loc[start:end]
    print(f"  Loaded {len(m1):,} M1 bars ({m1.index[0]} to {m1.index[-1]})")
    return m1


def main():
    # Load 2020-2022 test data
    m1 = load_clean_data("2020-01-01", "2022-12-31")

    # Step 1: Calibrate angle scales on this data
    print("\n" + "=" * 60)
    print("  STEP 1: ANGLE SCALE CALIBRATION")
    print("=" * 60)
    scale_results = calibrate_angle_scales(m1, vibration=72.0)

    # Extract best scales
    m5_scale = scale_results.get("M5", {}).get("best_scale", 1.0)
    h1_scale = scale_results.get("H1", {}).get("best_scale", 12.0)
    d1_scale = scale_results.get("D1", {}).get("best_scale", 72.0)
    print(f"\n  Calibrated scales: M5=${m5_scale}, H1=${h1_scale}, D1=${d1_scale}")

    # Step 2: Run FADE mode (baseline)
    print("\n" + "=" * 60)
    print("  STEP 2: BASELINE — FADE DIRECTION")
    print("=" * 60)
    fade_result = run_scalp_simulation(
        m1,
        starting_capital=20.0,
        vibration=12.0,  # Legacy V=12 for levels
        min_convergence=3,
        dataset_name="2020-2022 FADE",
        use_angle_direction=False,
    )

    # Step 3: Run ANGLE mode
    print("\n" + "=" * 60)
    print("  STEP 3: NEW — ANGLE DIRECTION")
    print("=" * 60)
    angle_result = run_scalp_simulation(
        m1,
        starting_capital=20.0,
        vibration=12.0,  # V=12 for Gann levels (Sq9, vibration multiples)
        min_convergence=3,
        dataset_name="2020-2022 ANGLE",
        use_angle_direction=True,
        m5_scale=m5_scale,
        h1_scale=h1_scale,
        d1_scale=d1_scale,
        require_multi_tf=True,
    )

    # Step 4: Run ANGLE mode without multi-TF requirement (more trades)
    print("\n" + "=" * 60)
    print("  STEP 4: ANGLE DIRECTION (no multi-TF requirement)")
    print("=" * 60)
    angle_notf_result = run_scalp_simulation(
        m1,
        starting_capital=20.0,
        vibration=12.0,
        min_convergence=3,
        dataset_name="2020-2022 ANGLE-noTF",
        use_angle_direction=True,
        m5_scale=m5_scale,
        h1_scale=h1_scale,
        d1_scale=d1_scale,
        require_multi_tf=False,
    )

    # Comparison summary
    print("\n" + "=" * 60)
    print("  COMPARISON SUMMARY")
    print("=" * 60)
    for name, res in [("FADE", fade_result), ("ANGLE+TF", angle_result), ("ANGLE-noTF", angle_notf_result)]:
        if res.get("total_trades", 0) > 0:
            print(f"\n  {name}:")
            print(f"    Trades:     {res['total_trades']} ({res['trades_per_day']:.1f}/day)")
            print(f"    Win rate:   {res['win_rate']:.1%}")
            print(f"    R:R:        {abs(res['avg_win']/res['avg_loss']):.2f}" if res['avg_loss'] else "    R:R: N/A")
            print(f"    Max DD:     {res['max_drawdown']:.1%}")
            print(f"    Final eq:   ${res['final_equity']:.2f}")
        else:
            print(f"\n  {name}: No trades generated")


if __name__ == "__main__":
    main()
