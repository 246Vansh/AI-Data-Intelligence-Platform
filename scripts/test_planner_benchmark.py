import statistics
import time

import pandas as pd

from data_engine.metadata import get_metadata

from ai.fast_planner import FastPlanner
from ai.planner import create_analysis_plan, get_provider


# =========================================================
# CONFIGURATION
# =========================================================

RUNS = 2

QUESTIONS = [
    "Show total revenue",
    "Show average revenue",
    "Show maximum revenue",
    "Show minimum revenue",
    "Show the top 5 categories by total revenue",
    "Show the bottom 3 categories by average revenue",
]


# =========================================================
# BENCHMARK DATASET
# =========================================================
#
# Deliberately generic and created entirely in memory.
#
# This benchmark must not depend on:
#   - Walmart
#   - a specific business domain
#   - data/raw/
#   - an external CSV file
#   - a user-uploaded dataset
#
# The dataset only exists to provide realistic metadata to
# the planners being benchmarked.
# =========================================================


def create_benchmark_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "category": [
                "A",
                "A",
                "A",
                "B",
                "B",
                "B",
                "C",
                "C",
                "C",
                "D",
                "D",
                "D",
            ],
            "date": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-08",
                    "2026-01-15",
                    "2026-01-01",
                    "2026-01-08",
                    "2026-01-15",
                    "2026-01-01",
                    "2026-01-08",
                    "2026-01-15",
                    "2026-01-01",
                    "2026-01-08",
                    "2026-01-15",
                ]
            ),
            "revenue": [
                1000,
                1200,
                1100,
                1500,
                1700,
                1600,
                800,
                900,
                850,
                2000,
                2200,
                2100,
            ],
        }
    )


# =========================================================
# FAST PLANNER BENCHMARK
# =========================================================


def benchmark_fast_planner(
    planner,
    question,
    metadata,
):
    timings = []

    for _ in range(RUNS):
        start = time.perf_counter()

        planner.create_plan(
            question=question,
            metadata=metadata,
        )

        elapsed = (time.perf_counter() - start) * 1000

        timings.append(elapsed)

    return timings


# =========================================================
# PLANNER ROUTER BENCHMARK
# =========================================================


def benchmark_planner_router(
    question,
    metadata,
):
    timings = []

    for _ in range(RUNS):
        start = time.perf_counter()

        create_analysis_plan(
            user_question=question,
            metadata=metadata,
        )

        elapsed = (time.perf_counter() - start) * 1000

        timings.append(elapsed)

    return timings


# =========================================================
# DIRECT CLAUDE PLANNER BENCHMARK
# =========================================================


def benchmark_claude_planner(
    provider,
    question,
    metadata,
):
    timings = []

    for _ in range(RUNS):
        start = time.perf_counter()

        provider.create_analysis_plan(
            user_question=question,
            metadata=metadata,
        )

        elapsed = (time.perf_counter() - start) * 1000

        timings.append(elapsed)

    return timings


# =========================================================
# STATISTICS
# =========================================================


def print_statistics(
    label,
    timings,
):
    average = statistics.mean(timings)
    minimum = min(timings)
    maximum = max(timings)

    print(f"\n{label}")
    print("-" * 45)

    print(f"runs    : {len(timings)}")
    print(f"average : {average:.2f} ms")
    print(f"minimum : {minimum:.2f} ms")
    print(f"maximum : {maximum:.2f} ms")

    return average


# =========================================================
# MAIN
# =========================================================


def main():

    print("=" * 60)
    print("PLANNER PERFORMANCE BENCHMARK")
    print("=" * 60)

    # -----------------------------------------------------
    # Create generic benchmark dataset
    # -----------------------------------------------------

    print("\nCreating generic benchmark dataset...")

    df = create_benchmark_dataset()

    print(f"Dataset rows    : {len(df)}")
    print(f"Dataset columns : {len(df.columns)}")

    # -----------------------------------------------------
    # Generate metadata
    # -----------------------------------------------------

    print("\nGenerating metadata...")

    metadata = get_metadata(df)

    # -----------------------------------------------------
    # Create planners
    # -----------------------------------------------------

    fast_planner = FastPlanner()
    provider = get_provider()

    # -----------------------------------------------------
    # Results
    # -----------------------------------------------------

    overall_fast = []
    overall_router = []
    overall_claude = []

    # =====================================================
    # QUESTION LOOP
    # =====================================================

    for question in QUESTIONS:
        print("\n")
        print("=" * 60)
        print("QUESTION")
        print("=" * 60)

        print(question)

        # =================================================
        # FAST PLANNER
        # =================================================

        fast_timings = benchmark_fast_planner(
            planner=fast_planner,
            question=question,
            metadata=metadata,
        )

        fast_average = print_statistics(
            "FAST PLANNER",
            fast_timings,
        )

        # =================================================
        # ROUTER
        # =================================================

        print("\nCalling Planner Router...")

        router_timings = benchmark_planner_router(
            question=question,
            metadata=metadata,
        )

        router_average = print_statistics(
            "PLANNER ROUTER",
            router_timings,
        )

        # =================================================
        # DIRECT CLAUDE
        # =================================================

        print("\nCalling Claude directly...")

        claude_timings = benchmark_claude_planner(
            provider=provider,
            question=question,
            metadata=metadata,
        )

        claude_average = print_statistics(
            "DIRECT CLAUDE PLANNER",
            claude_timings,
        )

        # -------------------------------------------------
        # Store averages
        # -------------------------------------------------

        overall_fast.append(fast_average)
        overall_router.append(router_average)
        overall_claude.append(claude_average)

        # =================================================
        # ROUTER vs FAST
        # =================================================

        if fast_average > 0:
            router_ratio = router_average / fast_average

            print(f"\nROUTER / FAST: {router_ratio:.2f}x")

        # =================================================
        # CLAUDE vs FAST
        # =================================================

        if fast_average > 0:
            claude_ratio = claude_average / fast_average

            print(f"CLAUDE / FAST: {claude_ratio:.2f}x")

    # =====================================================
    # OVERALL RESULTS
    # =====================================================

    print("\n")
    print("=" * 60)
    print("OVERALL RESULTS")
    print("=" * 60)

    fast_overall_average = statistics.mean(overall_fast)

    router_overall_average = statistics.mean(overall_router)

    claude_overall_average = statistics.mean(overall_claude)

    print(f"\nFast Planner average    : {fast_overall_average:.2f} ms")

    print(f"Planner Router average  : {router_overall_average:.2f} ms")

    print(f"Direct Claude average   : {claude_overall_average:.2f} ms")

    # -----------------------------------------------------
    # Performance ratios
    # -----------------------------------------------------

    if fast_overall_average > 0:
        router_ratio = router_overall_average / fast_overall_average

        claude_ratio = claude_overall_average / fast_overall_average

        print(f"\nRouter / Fast           : {router_ratio:.2f}x")

        print(f"Claude / Fast           : {claude_ratio:.2f}x")

    # =====================================================
    # ARCHITECTURE
    # =====================================================

    print("\n")
    print("=" * 60)
    print("ARCHITECTURE RESULT")
    print("=" * 60)

    print(
        "\nDeterministic questions"
        "\n→ Planner Router"
        "\n→ Fast Planner"
        "\n→ Plan Validator"
        "\n→ Data Engine"
    )

    print(
        "\nComplex / ambiguous questions"
        "\n→ Planner Router"
        "\n→ Claude Planner"
        "\n→ Plan Adapter"
        "\n→ Plan Validator"
        "\n→ Data Engine"
    )

    print("\nDirect Claude benchmark\n→ Claude Planner\n→ Provider")

    print("\nThe validator remains mandatory for the actual analysis pipeline.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
