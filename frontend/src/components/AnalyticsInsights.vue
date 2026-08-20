<script setup>
import { computed } from "vue";

const props = defineProps({
    result: {
        type: Object,
        required: true,
    },
});

/*
|--------------------------------------------------------------------------
| Backend response
|--------------------------------------------------------------------------
|
| Expected:
|
| result.insights = {
|     insights: [...]
| }
|
| Each insight can contain:
| - type
| - title
| - description
| - evidence
|
*/

const insights = computed(() => {
    const value = props.result?.insights?.insights;

    return Array.isArray(value) ? value : [];
});

const insightCount = computed(() => insights.value.length);

const hasInsights = computed(() => insightCount.value > 0);

function getInsightMeta(type) {
    const metadata = {
        highest: {
            label: "Highest",
            icon: "↑",
            description: "Peak value identified",
            classes: {
                wrapper:
                    "border-emerald-100 bg-gradient-to-br from-emerald-50/70 to-white",
                icon: "bg-emerald-100 text-emerald-600",
                badge: "bg-emerald-100 text-emerald-700",
                accent: "bg-emerald-500",
            },
        },

        lowest: {
            label: "Lowest",
            icon: "↓",
            description: "Minimum value identified",
            classes: {
                wrapper:
                    "border-rose-100 bg-gradient-to-br from-rose-50/70 to-white",
                icon: "bg-rose-100 text-rose-600",
                badge: "bg-rose-100 text-rose-700",
                accent: "bg-rose-500",
            },
        },

        trend: {
            label: "Trend",
            icon: "↗",
            description: "Pattern detected in the data",
            classes: {
                wrapper:
                    "border-blue-100 bg-gradient-to-br from-blue-50/70 to-white",
                icon: "bg-blue-100 text-blue-600",
                badge: "bg-blue-100 text-blue-700",
                accent: "bg-blue-500",
            },
        },

        difference: {
            label: "Difference",
            icon: "↔",
            description: "Difference between observed values",
            classes: {
                wrapper:
                    "border-amber-100 bg-gradient-to-br from-amber-50/70 to-white",
                icon: "bg-amber-100 text-amber-600",
                badge: "bg-amber-100 text-amber-700",
                accent: "bg-amber-500",
            },
        },

        coverage: {
            label: "Coverage",
            icon: "◌",
            description: "Data availability check",
            classes: {
                wrapper:
                    "border-violet-100 bg-gradient-to-br from-violet-50/70 to-white",
                icon: "bg-violet-100 text-violet-600",
                badge: "bg-violet-100 text-violet-700",
                accent: "bg-violet-500",
            },
        },
    };

    return (
        metadata[type] || {
            label: "Insight",
            icon: "✦",
            description: "AI-generated observation",
            classes: {
                wrapper:
                    "border-slate-100 bg-gradient-to-br from-slate-50/70 to-white",
                icon: "bg-slate-100 text-slate-600",
                badge: "bg-slate-100 text-slate-700",
                accent: "bg-slate-500",
            },
        }
    );
}

/*
|--------------------------------------------------------------------------
| Formatting
|--------------------------------------------------------------------------
*/

function formatValue(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    if (typeof value !== "number") {
        return String(value);
    }

    return value.toLocaleString(undefined, {
        maximumFractionDigits: 2,
    });
}

function formatEvidenceDate(value) {
    if (!value) {
        return "";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleDateString(undefined, {
        month: "short",
        year: "numeric",
    });
}

function getEvidenceRows(evidence) {
    if (!evidence) {
        return [];
    }

    if (Array.isArray(evidence.rows)) {
        return evidence.rows;
    }

    if (evidence.row) {
        return [evidence.row];
    }

    return [];
}

function getEvidenceLabel(row) {
    if (!row) {
        return "";
    }

    const dateValue = row.Date || row.date;

    if (dateValue) {
        return formatEvidenceDate(dateValue);
    }

    const entries = Object.entries(row);

    if (!entries.length) {
        return "";
    }

    return String(entries[0][1]);
}

function getEvidenceValue(row, evidence) {
    if (!row) {
        return null;
    }

    if (
        evidence?.column &&
        row[evidence.column] !== undefined
    ) {
        return row[evidence.column];
    }

    const numericEntry = Object.entries(row).find(
        ([key, value]) =>
            key !== "Date" &&
            key !== "date" &&
            typeof value === "number",
    );

    return numericEntry ? numericEntry[1] : null;
}

function getCoveragePercentage(evidence) {
    if (!evidence) {
        return 0;
    }

    const observed = Number(evidence.observed_periods);
    const expected = Number(evidence.expected_periods);

    if (
        !Number.isFinite(observed) ||
        !Number.isFinite(expected) ||
        expected <= 0
    ) {
        return 0;
    }

    return Math.min(
        Math.max((observed / expected) * 100, 0),
        100,
    );
}

function getCoverageSummary(evidence) {
    if (
        evidence?.observed_periods !== undefined &&
        evidence?.expected_periods !== undefined
    ) {
        return `${evidence.observed_periods} of ${evidence.expected_periods} periods`;
    }

    return null;
}

function getCoverageStatus(evidence) {
    const percentage = getCoveragePercentage(evidence);

    if (percentage >= 100) {
        return {
            label: "Complete",
            classes: "bg-emerald-50 text-emerald-700",
        };
    }

    if (percentage >= 75) {
        return {
            label: "Mostly complete",
            classes: "bg-amber-50 text-amber-700",
        };
    }

    return {
        label: "Incomplete",
        classes: "bg-rose-50 text-rose-700",
    };
}

function hasMissingPeriods(evidence) {
    return Array.isArray(evidence?.missing_periods) &&
        evidence.missing_periods.length > 0;
}

function getEvidenceColumn(evidence) {
    if (evidence?.column) {
        return evidence.column;
    }

    return "Value";
}
</script>

<template>
    <section
        v-if="hasInsights"
        class="mt-6 overflow-hidden rounded-[20px] border border-[#e7e5f2] bg-white shadow-[0_8px_30px_rgba(15,23,42,0.04)]"
    >
        <!-- =========================================================
             HEADER
        ========================================================== -->

        <div
            class="border-b border-[#edf0f5] bg-gradient-to-r from-[#faf9ff] via-white to-[#faf9ff] px-5 py-5"
        >
            <div
                class="flex items-center justify-between gap-4 max-[600px]:items-start"
            >
                <div class="flex min-w-0 items-center gap-3">
                    <div
                        class="flex h-11 w-11 shrink-0 items-center justify-center rounded-[13px] bg-gradient-to-br from-[#ede9fe] to-[#e0e7ff] text-lg text-[#6d28d9] shadow-[0_4px_12px_rgba(124,58,237,0.10)]"
                    >
                        ✦
                    </div>

                    <div class="min-w-0">
                        <div class="flex items-center gap-2">
                            <h4
                                class="m-0 truncate text-[17px] font-bold tracking-[-0.2px] text-[#172033]"
                            >
                                AI Insights
                            </h4>

                            <span
                                class="hidden rounded-full bg-[#f3efff] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.4px] text-[#6d28d9] sm:inline-flex"
                            >
                                Evidence-backed
                            </span>
                        </div>

                        <p
                            class="mt-1 mb-0 text-[11px] leading-5 text-[#98a2b3]"
                        >
                            Key observations generated from your analysis
                        </p>
                    </div>
                </div>

                <div
                    class="flex shrink-0 items-center gap-2 rounded-full border border-[#e9e3ff] bg-[#f8f7ff] px-3 py-[7px] text-[10px] font-bold text-[#6d28d9]"
                >
                    <span
                        class="h-[6px] w-[6px] rounded-full bg-[#7c3aed]"
                    ></span>

                    {{ insightCount }}
                    {{ insightCount === 1 ? "insight" : "insights" }}
                </div>
            </div>
        </div>

        <!-- =========================================================
             INSIGHTS
        ========================================================== -->

        <div class="grid grid-cols-1 gap-3 p-5">
            <article
                v-for="(insight, index) in insights"
                :key="`${insight.type || 'insight'}-${index}`"
                class="relative overflow-hidden rounded-[15px] border p-4 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-[0_8px_22px_rgba(15,23,42,0.06)]"
                :class="getInsightMeta(insight.type).classes.wrapper"
            >
                <!-- Accent -->
                <div
                    class="absolute left-0 top-0 h-full w-[3px]"
                    :class="getInsightMeta(insight.type).classes.accent"
                ></div>

                <!-- =================================================
                     INSIGHT HEADER
                ================================================== -->

                <div class="flex items-start gap-3">
                    <div
                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-[11px] text-base font-bold"
                        :class="getInsightMeta(insight.type).classes.icon"
                    >
                        {{ getInsightMeta(insight.type).icon }}
                    </div>

                    <div class="min-w-0 flex-1">
                        <div
                            class="mb-1.5 flex flex-wrap items-center gap-2"
                        >
                            <span
                                class="rounded-full px-2 py-1 text-[9px] font-bold uppercase tracking-[0.45px]"
                                :class="
                                    getInsightMeta(insight.type)
                                        .classes.badge
                                "
                            >
                                {{
                                    getInsightMeta(insight.type).label
                                }}
                            </span>

                            <span
                                class="text-[10px] text-[#98a2b3]"
                            >
                                {{
                                    getInsightMeta(insight.type)
                                        .description
                                }}
                            </span>
                        </div>

                        <h5
                            class="m-0 text-[14px] font-bold leading-[1.45] text-[#172033]"
                        >
                            {{ insight.title || "Untitled insight" }}
                        </h5>

                        <p
                            v-if="insight.description"
                            class="mt-1.5 mb-0 text-[12px] leading-[1.7] text-[#667085]"
                        >
                            {{ insight.description }}
                        </p>
                    </div>
                </div>

                <!-- =================================================
                     EVIDENCE
                ================================================== -->

                <div
                    v-if="insight.evidence"
                    class="mt-4 border-t border-black/[0.05] pt-3"
                >
                    <!-- =================================================
                         COVERAGE
                    ================================================== -->

                    <div
                        v-if="
                            insight.type === 'coverage' &&
                            insight.evidence.observed_periods !==
                                undefined
                        "
                        class="rounded-[11px] bg-white/80 p-3.5"
                    >
                        <div
                            class="mb-3 flex items-center justify-between gap-3"
                        >
                            <div>
                                <div
                                    class="text-[10px] font-bold uppercase tracking-[0.45px] text-[#98a2b3]"
                                >
                                    Data coverage
                                </div>

                                <div
                                    class="mt-1 text-[12px] font-semibold text-[#475467]"
                                >
                                    {{
                                        getCoverageSummary(
                                            insight.evidence,
                                        )
                                    }}
                                </div>
                            </div>

                            <span
                                class="rounded-full px-2.5 py-1 text-[9px] font-bold"
                                :class="
                                    getCoverageStatus(
                                        insight.evidence,
                                    ).classes
                                "
                            >
                                {{
                                    getCoverageStatus(
                                        insight.evidence,
                                    ).label
                                }}
                            </span>
                        </div>

                        <div
                            class="h-2 overflow-hidden rounded-full bg-[#e9e7f2]"
                        >
                            <div
                                class="h-full rounded-full bg-gradient-to-r from-[#7c3aed] to-[#6366f1] transition-all duration-500"
                                :style="{
                                    width:
                                        getCoveragePercentage(
                                            insight.evidence,
                                        ) + '%',
                                }"
                            ></div>
                        </div>

                        <div
                            v-if="hasMissingPeriods(insight.evidence)"
                            class="mt-3"
                        >
                            <div
                                class="mb-1.5 text-[10px] font-semibold text-[#667085]"
                            >
                                Missing periods
                            </div>

                            <div class="flex flex-wrap gap-1.5">
                                <span
                                    v-for="period in insight.evidence
                                        .missing_periods"
                                    :key="period"
                                    class="rounded-md border border-[#e9e3ff] bg-[#f8f7ff] px-2 py-1 text-[9px] font-medium text-[#6d28d9]"
                                >
                                    {{ period }}
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- =================================================
                         MULTI-ROW EVIDENCE
                    ================================================== -->

                    <div
                        v-else-if="
                            Array.isArray(insight.evidence.rows)
                        "
                        class="rounded-[11px] bg-white/80 p-3.5"
                    >
                        <div
                            class="mb-3 flex items-center justify-between"
                        >
                            <div
                                class="text-[10px] font-bold uppercase tracking-[0.45px] text-[#98a2b3]"
                            >
                                Supporting data
                            </div>

                            <span
                                class="text-[9px] font-semibold text-[#98a2b3]"
                            >
                                {{ insight.evidence.rows.length }}
                                points
                            </span>
                        </div>

                        <div
                            class="flex items-center gap-2 overflow-x-auto pb-1"
                        >
                            <template
                                v-for="(
                                    row, rowIndex
                                ) in insight.evidence.rows"
                                :key="rowIndex"
                            >
                                <div
                                    class="min-w-[125px] rounded-[10px] border border-[#edf0f5] bg-white px-3 py-2.5 shadow-[0_2px_8px_rgba(15,23,42,0.025)]"
                                >
                                    <div
                                        class="truncate text-[9px] font-medium text-[#98a2b3]"
                                    >
                                        {{
                                            getEvidenceLabel(row)
                                        }}
                                    </div>

                                    <div
                                        class="mt-1 text-[12px] font-bold text-[#172033]"
                                    >
                                        {{
                                            formatValue(
                                                getEvidenceValue(
                                                    row,
                                                    insight.evidence,
                                                ),
                                            )
                                        }}
                                    </div>
                                </div>

                                <span
                                    v-if="
                                        rowIndex <
                                        insight.evidence.rows
                                            .length -
                                            1
                                    "
                                    class="shrink-0 text-[16px] text-[#c4b5fd]"
                                >
                                    →
                                </span>
                            </template>
                        </div>
                    </div>

                    <!-- =================================================
                         SINGLE ROW EVIDENCE
                    ================================================== -->

                    <div
                        v-else-if="insight.evidence.row"
                        class="flex items-center justify-between gap-5 rounded-[11px] bg-white/80 p-3.5 max-[550px]:items-start max-[550px]:flex-col"
                    >
                        <div class="min-w-0">
                            <div
                                class="text-[9px] font-bold uppercase tracking-[0.45px] text-[#98a2b3]"
                            >
                                Evidence
                            </div>

                            <div
                                class="mt-1 truncate text-[11px] font-semibold text-[#475467]"
                            >
                                {{
                                    getEvidenceLabel(
                                        insight.evidence.row,
                                    )
                                }}
                            </div>
                        </div>

                        <div
                            class="shrink-0 text-right max-[550px]:text-left"
                        >
                            <div
                                class="text-[9px] font-bold uppercase tracking-[0.45px] text-[#98a2b3]"
                            >
                                {{
                                    getEvidenceColumn(
                                        insight.evidence,
                                    )
                                }}
                            </div>

                            <div
                                class="mt-1 text-[15px] font-bold tracking-[-0.2px] text-[#172033]"
                            >
                                {{
                                    formatValue(
                                        insight.evidence.value,
                                    )
                                }}
                            </div>
                        </div>
                    </div>
                </div>
            </article>
        </div>
    </section>
</template>