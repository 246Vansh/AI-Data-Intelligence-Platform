import time
import statistics

from backend.dependencies import get_walmart_data
from data_engine.metadata import get_metadata

from ai.fast_planner import FastPlanner
from ai.planner import create_analysis_plan


# =========================================================
# CONFIGURATION
# =========================================================

RUNS = 2

QUESTIONS = [
    "Show total revenue",
    "Show average revenue",
    "Show maximum revenue",
    "Show minimum revenue",
    "Show the top 5 regions by revenue",
    "Show the bottom 3 regions by average revenue",
]


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
# AI PLANNER BENCHMARK
# =========================================================


def benchmark_ai_planner(
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
    # Load dataset
    # -----------------------------------------------------

    print("\nLoading dataset...")

    df = get_walmart_data()

    print(f"Dataset rows    : {len(df)}")

    print(f"Dataset columns : {len(df.columns)}")

    # -----------------------------------------------------
    # Generate metadata
    # -----------------------------------------------------

    print("\nGenerating metadata...")

    metadata = get_metadata(df)

    # -----------------------------------------------------
    # Create Fast Planner
    # -----------------------------------------------------

    fast_planner = FastPlanner()

    # -----------------------------------------------------
    # Results
    # -----------------------------------------------------

    overall_fast = []
    overall_ai = []

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
        # AI PLANNER
        # =================================================

        print("\nCalling Claude...")

        ai_timings = benchmark_ai_planner(
            question=question,
            metadata=metadata,
        )

        ai_average = print_statistics(
            "AI PLANNER",
            ai_timings,
        )

        # -------------------------------------------------
        # Store averages
        # -------------------------------------------------

        overall_fast.append(fast_average)

        overall_ai.append(ai_average)

        # =================================================
        # SPEEDUP
        # =================================================

        if fast_average > 0:
            speedup = ai_average / fast_average

            print(f"\nSPEEDUP: {speedup:.2f}x")

    # =====================================================
    # OVERALL RESULTS
    # =====================================================

    print("\n")
    print("=" * 60)
    print("OVERALL RESULTS")
    print("=" * 60)

    fast_overall_average = statistics.mean(overall_fast)

    ai_overall_average = statistics.mean(overall_ai)

    overall_speedup = ai_overall_average / fast_overall_average

    print(f"\nFast Planner average : {fast_overall_average:.2f} ms")

    print(f"AI Planner average   : {ai_overall_average:.2f} ms")

    print(f"Overall speedup      : {overall_speedup:.2f}x")

    # =====================================================
    # ARCHITECTURE
    # =====================================================

    print("\n")
    print("=" * 60)
    print("ARCHITECTURE RESULT")
    print("=" * 60)

    print("\nDeterministic questions\n→ Fast Planner\n→ Plan Validator\n→ Data Engine")

    print(
        "\nComplex / ambiguous questions"
        "\n→ Claude Planner"
        "\n→ Plan Adapter"
        "\n→ Plan Validator"
        "\n→ Data Engine"
    )

    print("\nThe validator remains mandatory for both paths.")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
