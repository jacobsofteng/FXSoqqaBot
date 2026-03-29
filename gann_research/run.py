#!/usr/bin/env python3
"""
Gann Research Runner — Execute all hypothesis tests.

Usage:
    python -m gann_research.run [--years START END] [--tests TEST1,TEST2,...]

Train/test split: 2015-2019 (train) | 2020-2026 (test)
"""

import sys
import time
import argparse
from datetime import datetime

from . import data_loader
from . import calibrate as gann_calibrate
from . import scalp_sim


def print_banner():
    print("=" * 70)
    print("  GANN FORMULA EMPIRICAL VALIDATION")
    print("  XAUUSD M1 Data | 2015-2026 | 11 years")
    print("  Anti-overfitting: Bonferroni, permutation tests, train/test split")
    print("=" * 70)


def print_summary(results: list):
    print("\n" + "=" * 70)
    print("  SUMMARY OF ALL TESTS")
    print("=" * 70)

    # Separate train and test results
    train_results = [r for r in results if r.dataset == "train"]
    test_results = [r for r in results if r.dataset == "test"]

    print(f"\n{'Test':<35} {'Train Hit%':>10} {'Test Hit%':>10} {'Effect':>8} {'Sig?':>6}")
    print("-" * 70)

    # Match train/test pairs
    test_names = set(r.name for r in results)
    for name in sorted(test_names):
        train = next((r for r in train_results if r.name == name), None)
        test = next((r for r in test_results if r.name == name), None)

        train_hr = f"{train.hit_rate:.1%}" if train and train.n_samples > 0 else "N/A"
        test_hr = f"{test.hit_rate:.1%}" if test and test.n_samples > 0 else "N/A"
        effect = f"{train.effect_size:+.1%}" if train and train.n_samples > 0 else "N/A"

        # Significance markers
        if train and train.is_significant and train.is_practically_significant:
            sig = "***"
        elif train and train.is_significant:
            sig = "**"
        elif train and train.p_value < 0.05:
            sig = "*"
        else:
            sig = ""

        # Overfitting check: if train >> test, flag it
        overfit = ""
        if train and test and train.n_samples > 0 and test.n_samples > 0:
            if train.hit_rate > test.hit_rate * 1.3 and train.hit_rate > 0.1:
                overfit = " [OVERFIT?]"

        print(f"  {name:<33} {train_hr:>10} {test_hr:>10} {effect:>8} {sig:>6}{overfit}")

    print()
    print("  Legend: *** = significant + practical (p_corrected<0.05, effect>10%)")
    print("          **  = statistically significant only")
    print("          *   = p<0.05 uncorrected (may be noise)")
    print("          [OVERFIT?] = train >> test (>30% degradation)")
    print()

    # Vibration constant specific output
    vib_results = [r for r in results if r.name == "Vibration Constant" and r.details.get("rankings")]
    for r in vib_results:
        print(f"\n  VIBRATION CONSTANT RANKINGS [{r.dataset}]:")
        rankings = r.details["rankings"]
        for name, data in sorted(rankings.items(), key=lambda x: x[1]["hit_rate"], reverse=True):
            print(f"    {name:12s}: v={data['vib_value']:>7.2f}  hit={data['hit_rate']:.1%}")

        override = r.details.get("override_4x_72", {})
        if override.get("total"):
            print(f"    4x override (72): {override['hits']}/{override['total']} = {override['hits']/override['total']:.1%}")


def main():
    parser = argparse.ArgumentParser(description="Gann Formula Empirical Validation")
    parser.add_argument("--start-year", type=int, default=2009)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--train-end", default="2019-12-31")
    parser.add_argument("--tests", help="Comma-separated test names to run (default: all)")
    args = parser.parse_args()

    print_banner()

    # Load data
    print("\nLoading XAUUSD M1 data...")
    t0 = time.time()
    m1 = data_loader.load_years(args.start_year, args.end_year)
    print(f"  Loaded in {time.time() - t0:.1f}s")

    # Split
    print("\nSplitting train/test...")
    train, test = data_loader.split_train_test(m1, args.train_end)

    # Run M5 scalping simulation
    print(f"\n{'='*70}")
    print(f"  GANN M5 SCALPING SIMULATION")
    print(f"  $20 capital, 1:500 leverage, RoboForex ECN")
    print(f"{'='*70}")

    t0 = time.time()

    print(f"\n--- TRAIN ({len(train):,} M1 bars) ---")
    train_result = scalp_sim.run_scalp_simulation(
        train, starting_capital=1000.0, vibration=12.0,
        min_convergence=2, dataset_name="train"
    )

    print(f"\n--- TEST ({len(test):,} M1 bars) ---")
    test_result = scalp_sim.run_scalp_simulation(
        test, starting_capital=1000.0, vibration=12.0,
        min_convergence=2, dataset_name="test"
    )

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed:.1f}s")

    return {"train": train_result, "test": test_result}


if __name__ == "__main__":
    main()
