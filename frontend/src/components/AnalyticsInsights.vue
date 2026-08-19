<script setup>
import { computed } from "vue";

const props = defineProps({
    result: {
        type: Object,
        required: true,
    },
});

const insights = computed(() => {
    return props.result?.insights?.insights || [];
});

function getInsightMeta(type) {
    const metadata = {
        highest: {
            label: "Highest",
            icon: "↑",
            classes: {
                wrapper: "border-emerald-100 bg-emerald-50/40",
                icon: "bg-emerald-100 text-emerald-600",
                badge: "bg-emerald-100 text-emerald-700",
            },
        },

        lowest: {
            label: "Lowest",
            icon: "↓",
            classes: {
                wrapper: "border-rose-100 bg-rose-50/40",
                icon: "bg-rose-100 text-rose-600",
                badge: "bg-rose-100 text-rose-700",
            },
        },

        trend: {
            label: "Trend",
            icon: "↗",
            classes: {
                wrapper: "border-blue-100 bg-blue-50/40",
                icon: "bg-blue-100 text-blue-600",
                badge: "bg-blue-100 text-blue-700",
            },
        },

        difference: {
            label: "Difference",
            icon: "↔",
            classes: {
                wrapper: "border-amber-100 bg-amber-50/40",
                icon: "bg-amber-100 text-amber-600",
                badge: "bg-amber-100 text-amber-700",
            },
        },

        coverage: {
            label: "Coverage",
            icon: "◌",
            classes: {
                wrapper: "border-violet-100 bg-violet-50/40",
                icon: "bg-violet-100 text-violet-600",
                badge: "bg-violet-100 text-violet-700",
            },
        },
    };

    return (
        metadata[type] || {
            label: "Insight",
            icon: "✦",
            classes: {
                wrapper: "border-slate-100 bg-slate-50/40",
                icon: "bg-slate-100 text-slate-600",
                badge: "bg-slate-100 text-slate-700",
            },
        }
    );
}

function formatValue(value) {
    if (typeof value !== "number") {
        return value;
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
        return value;
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

    if (evidence?.column && row[evidence.column] !== undefined) {
        return row[evidence.column];
    }

    const numericEntry = Object.entries(row).find(
        ([key, value]) =>
            key !== "Date" &&
            key !== "date" &&
            typeof value === "number"
    );

    return numericEntry ? numericEntry[1] : null;
}

function getCoverageSummary(evidence) {
    if (!evidence) {
        return null;
    }

    if (
        evidence.observed_periods !== undefined &&
        evidence.expected_periods !== undefined
    ) {
        return `${evidence.observed_periods} of ${evidence.expected_periods} periods`;
    }

    return null;
}
</script>

<template>
    <section
        v-if="insights.length"
        class="mt-6 rounded-[18px] border border-[#e7e5f2] bg-gradient-to-br from-white to-[#faf9ff] p-5"
    >
        <!-- Header -->
        <div
            class="mb-5 flex items-center justify-between gap-4 max-[650px]:items-start"
        >
            <div class="flex items-center gap-3">
                <div
                    class="flex h-10 w-10 items-center justify-center rounded-[11px] bg-gradient-to-br from-[#ede9fe] to-[#e0e7ff] text-lg text-[#6d28d9]"
                >
                    ✦
                </div>

                <div>
                    <h4 class="m-0 text-[17px] font-bold text-[#172033]">
                        AI Insights
                    </h4>

                    <p class="mt-1 text-[11px] text-[#98a2b3]">
                        Evidence-backed observations from your analysis
                    </p>
                </div>
            </div>

            <span
                class="whitespace-nowrap rounded-full bg-[#f3efff] px-[10px] py-[6px] text-[10px] font-bold text-[#6d28d9]"
            >
                {{ insights.length }}
                {{ insights.length === 1 ? "insight" : "insights" }}
            </span>
        </div>

        <!-- Insights -->
        <div class="grid grid-cols-1 gap-3">
            <article
                v-for="(insight, index) in insights"
                :key="`${insight.type}-${index}`"
                class="rounded-[14px] border p-4 transition-all duration-200 hover:-translate-y-[1px] hover:shadow-sm"
                :class="getInsightMeta(insight.type).classes.wrapper"
            >
                <!-- Insight Header -->
                <div class="flex items-start gap-3">
                    <div
                        class="flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] text-base font-bold"
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
                                    getInsightMeta(insight.type).classes.badge
                                "
                            >
                                {{ getInsightMeta(insight.type).label }}
                            </span>
                        </div>

                        <h5
                            class="m-0 text-[14px] font-bold leading-[1.4] text-[#172033]"
                        >
                            {{ insight.title }}
                        </h5>

                        <p
                            class="mt-1.5 mb-0 text-[12px] leading-[1.65] text-[#667085]"
                        >
                            {{ insight.description }}
                        </p>
                    </div>
                </div>

                <!-- Evidence -->
                <div
                    v-if="insight.evidence"
                    class="mt-4 border-t border-black/[0.05] pt-3"
                >
                    <!-- Coverage Evidence -->
                    <div
                        v-if="
                            insight.type === 'coverage' &&
                            insight.evidence.observed_periods !== undefined
                        "
                        class="rounded-[10px] bg-white/70 p-3"
                    >
                        <div
                            class="mb-2 flex items-center justify-between gap-3"
                        >
                            <span
                                class="text-[10px] font-semibold uppercase tracking-[0.4px] text-[#98a2b3]"
                            >
                                Data coverage
                            </span>

                            <span
                                class="text-[11px] font-bold text-[#475467]"
                            >
                                {{
                                    getCoverageSummary(insight.evidence)
                                }}
                            </span>
                        </div>

                        <div
                            class="h-2 overflow-hidden rounded-full bg-[#e9e7f2]"
                        >
                            <div
                                class="h-full rounded-full bg-[#7c3aed]"
                                :style="{
                                    width:
                                        Math.min(
                                            (insight.evidence
                                                .observed_periods /
                                                insight.evidence
                                                    .expected_periods) *
                                                100,
                                            100
                                        ) + '%',
                                }"
                            ></div>
                        </div>

                        <div
                            v-if="
                                insight.evidence.missing_periods?.length
                            "
                            class="mt-3"
                        >
                            <span
                                class="text-[10px] font-semibold text-[#667085]"
                            >
                                Missing:
                            </span>

                            <span
                                v-for="period in insight.evidence
                                    .missing_periods"
                                :key="period"
                                class="ml-1 inline-block rounded-md bg-[#f3efff] px-1.5 py-1 text-[9px] font-medium text-[#6d28d9]"
                            >
                                {{ period }}
                            </span>
                        </div>
                    </div>

                    <!-- Multi-row Evidence -->
                    <div
                        v-else-if="
                            Array.isArray(insight.evidence.rows)
                        "
                        class="rounded-[10px] bg-white/70 p-3"
                    >
                        <div
                            class="mb-2 text-[10px] font-semibold uppercase tracking-[0.4px] text-[#98a2b3]"
                        >
                            Supporting data
                        </div>

                        <div
                            class="flex items-end gap-2 overflow-x-auto pb-1"
                        >
                            <template
                                v-for="(row, rowIndex) in insight.evidence
                                    .rows"
                                :key="rowIndex"
                            >
                                <div
                                    class="min-w-[110px] rounded-[9px] border border-[#edf0f5] bg-white px-3 py-2"
                                >
                                    <div
                                        class="text-[9px] font-medium text-[#98a2b3]"
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
                                                    insight.evidence
                                                )
                                            )
                                        }}
                                    </div>
                                </div>

                                <span
                                    v-if="
                                        rowIndex <
                                        insight.evidence.rows.length - 1
                                    "
                                    class="mb-4 shrink-0 text-[#c4b5fd]"
                                >
                                    →
                                </span>
                            </template>
                        </div>
                    </div>

                    <!-- Single-row Evidence -->
                    <div
                        v-else-if="insight.evidence.row"
                        class="flex items-center justify-between gap-4 rounded-[10px] bg-white/70 p-3 max-[550px]:items-start max-[550px]:flex-col"
                    >
                        <div>
                            <div
                                class="text-[9px] font-semibold uppercase tracking-[0.4px] text-[#98a2b3]"
                            >
                                Evidence
                            </div>

                            <div
                                class="mt-1 text-[11px] font-semibold text-[#475467]"
                            >
                                {{
                                    getEvidenceLabel(
                                        insight.evidence.row
                                    )
                                }}
                            </div>
                        </div>

                        <div class="text-right max-[550px]:text-left">
                            <div
                                class="text-[9px] font-semibold uppercase tracking-[0.4px] text-[#98a2b3]"
                            >
                                {{
                                    insight.evidence.column ||
                                    "Value"
                                }}
                            </div>

                            <div
                                class="mt-1 text-[15px] font-bold text-[#172033]"
                            >
                                {{
                                    formatValue(
                                        insight.evidence.value
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