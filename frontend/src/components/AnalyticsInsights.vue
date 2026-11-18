<script setup>
import { computed } from "vue";

import Icon from "./ui/Icon.vue";
import StatusChip from "./ui/StatusChip.vue";

const props = defineProps({
    result: {
        type: Object,
        required: true,
    },
});

// =========================================================
// BACKEND RESPONSE
// =========================================================

const insights = computed(() => {
    const value = props.result?.insights?.insights;

    if (!Array.isArray(value)) {
        return [];
    }

    return value.filter(
        (item) =>
            item &&
            typeof item === "object",
    );
});

const insightCount = computed(
    () => insights.value.length,
);

const hasInsights = computed(
    () => insightCount.value > 0,
);

// The backend reports where the insight text came from. Deterministic
// insights are computed from the result rows, not written by a model,
// and should not be presented as AI output.
const isComputed = computed(
    () => props.result?.insight_source === "deterministic",
);

const allEvidenceBacked = computed(
    () =>
        hasInsights.value &&
        insights.value.every(
            (insight) =>
                insight.evidence &&
                typeof insight.evidence === "object",
        ),
);

const rowLimitReached = computed(
    () => props.result?.data?.row_limit_reached === true,
);

// =========================================================
// INSIGHT METADATA
// =========================================================

// Presentation only (Phase 5): labels, descriptions and branching are
// unchanged. `icon` is now an Icon.vue name instead of a glyph, and
// every type shares one restrained forest/sage treatment - the type is
// identified by its icon and label, never by color, and no type is
// colored as good or bad.
function getInsightMeta(type) {
    const metadata = {
        highest: {
            label: "Highest",
            icon: "crown",
            description: "Peak value identified",
            classes: {
                wrapper: "",
                icon: "bg-[#f4e8cc] text-[#b58a2c]",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        },

        lowest: {
            label: "Lowest",
            icon: "bar-chart",
            description: "Minimum value identified",
            classes: {
                wrapper: "",
                icon: "bg-[#e6eee1] text-forest",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        },

        trend: {
            label: "Trend",
            icon: "trend-up",
            description:
                "Pattern detected in the data",
            classes: {
                wrapper: "",
                icon: "bg-[#e6eee1] text-forest",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        },

        difference: {
            label: "Difference",
            icon: "compare",
            description:
                "Difference between observed values",
            classes: {
                wrapper: "",
                icon: "bg-[#e6eee1] text-forest",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        },

        coverage: {
            label: "Coverage",
            icon: "target",
            description:
                "Data availability check",
            classes: {
                wrapper: "",
                icon: "bg-[#e6eee1] text-forest",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        },
    };

    return (
        metadata[type] || {
            label: "Insight",
            icon: "sparkle",
            description:
                "Observation",
            classes: {
                wrapper: "",
                icon: "bg-[#e6eee1] text-forest",
                badge: "bg-sunken text-ink-muted",
                accent: "bg-sage",
            },
        }
    );
}

// =========================================================
// FORMATTING
// =========================================================

function formatValue(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    if (typeof value !== "number") {
        return String(value);
    }

    return value.toLocaleString("en-US", {
        maximumFractionDigits: 2,
    });
}

function formatEvidenceValue(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    if (typeof value === "number") {
        return formatValue(value);
    }

    return String(value);
}

// =========================================================
// EVIDENCE HELPERS
// =========================================================

function getEvidenceRows(evidence) {
    if (
        !evidence ||
        typeof evidence !== "object"
    ) {
        return [];
    }

    if (Array.isArray(evidence.rows)) {
        return evidence.rows.filter(
            (row) =>
                row &&
                typeof row === "object",
        );
    }

    if (
        evidence.row &&
        typeof evidence.row === "object"
    ) {
        return [evidence.row];
    }

    return [];
}

// =========================================================
// EVIDENCE LABEL
// =========================================================

function getEvidenceLabel(
    row,
    evidence = {},
) {
    if (
        !row ||
        typeof row !== "object"
    ) {
        return "";
    }

    // Explicit label from backend
    if (
        evidence?.label !== undefined &&
        evidence?.label !== null &&
        evidence.label !== ""
    ) {
        return String(evidence.label);
    }

    // Explicit dimension from backend
    if (
        evidence?.dimension &&
        row[evidence.dimension] !==
        undefined
    ) {
        return String(
            row[evidence.dimension],
        );
    }

    // Remove metric column
    const entries = Object.entries(row).filter(
        ([key]) =>
            key !== evidence?.column,
    );

    if (!entries.length) {
        return "";
    }

    // Prefer a non-numeric dimension
    const nonNumericEntry =
        entries.find(
            ([, value]) => {
                if (
                    value === null ||
                    value === undefined ||
                    value === ""
                ) {
                    return false;
                }

                return !Number.isFinite(
                    Number(value),
                );
            },
        );

    if (nonNumericEntry) {
        return String(
            nonNumericEntry[1],
        );
    }

    // Otherwise use first available field
    return String(entries[0][1]);
}

// =========================================================
// EVIDENCE VALUE
// =========================================================

function getEvidenceValue(
    row,
    evidence = {},
) {
    if (
        !row ||
        typeof row !== "object"
    ) {
        return null;
    }

    // Explicit value
    if (
        evidence?.value !== undefined &&
        evidence?.value !== null
    ) {
        return evidence.value;
    }

    // Explicit metric column
    if (
        evidence?.column &&
        row[evidence.column] !==
        undefined
    ) {
        return row[evidence.column];
    }

    // First numeric value
    const numericEntry =
        Object.entries(row).find(
            ([, value]) => {
                if (
                    value === null ||
                    value === undefined ||
                    value === ""
                ) {
                    return false;
                }

                const number =
                    Number(value);

                return Number.isFinite(
                    number,
                );
            },
        );

    return numericEntry
        ? numericEntry[1]
        : null;
}

// =========================================================
// COVERAGE
// =========================================================

function getCoveragePercentage(
    evidence,
) {
    if (!evidence) {
        return 0;
    }

    const observed = Number(
        evidence.observed_periods,
    );

    const expected = Number(
        evidence.expected_periods,
    );

    if (
        !Number.isFinite(observed) ||
        !Number.isFinite(expected) ||
        expected <= 0
    ) {
        return 0;
    }

    return Math.min(
        Math.max(
            (observed / expected) * 100,
            0,
        ),
        100,
    );
}

function getCoverageSummary(
    evidence,
) {
    if (
        evidence?.observed_periods !==
        undefined &&
        evidence?.expected_periods !==
        undefined
    ) {
        return `${evidence.observed_periods} of ${evidence.expected_periods} periods`;
    }

    return null;
}

function getCoverageStatus(
    evidence,
) {
    const percentage =
        getCoveragePercentage(
            evidence,
        );

    if (percentage >= 100) {
        return {
            label: "Complete",
            classes:
                "bg-emerald-50 text-emerald-700",
        };
    }

    if (percentage >= 75) {
        return {
            label: "Mostly complete",
            classes:
                "bg-amber-50 text-amber-700",
        };
    }

    return {
        label: "Incomplete",
        classes:
            "bg-rose-50 text-rose-700",
    };
}

function hasMissingPeriods(
    evidence,
) {
    return (
        Array.isArray(
            evidence?.missing_periods,
        ) &&
        evidence.missing_periods
            .length > 0
    );
}

function getEvidenceColumn(
    evidence,
) {
    return (
        evidence?.column ||
        "Value"
    );
}
</script>

<template>
    <!-- Rendered inside the Findings tab / accordion of the Analyze
         workspace, which provides the heading. Each finding: an icon
         tile for its kind, the statement, its short description, and
         the evidence it rests on one click away. -->
    <div v-if="hasInsights">

        <p v-if="rowLimitReached" role="note"
            class="mx-4 mb-1 mt-2 flex items-start gap-2 rounded-control bg-warn-soft px-3 py-2 text-caption text-warn-ink">
            <Icon name="warning" :size="14" class="mt-px" />
            Result hit its row limit - only facts that hold for the full grouping are shown.
        </p>

        <ol>
            <li v-for="(insight, index) in insights" :key="`${insight.type || 'insight'}-${index}`">
                <article class="flex gap-3.5 px-4 py-3">

                    <span class="grid h-10 w-10 shrink-0 place-items-center rounded-[10px]"
                        :class="getInsightMeta(insight.type).classes.icon"
                        :title="`${getInsightMeta(insight.type).label}: ${getInsightMeta(insight.type).description}`">
                        <Icon :name="getInsightMeta(insight.type).icon" :size="20" />
                        <span class="sr-only">{{ getInsightMeta(insight.type).label }}</span>
                    </span>

                    <div class="min-w-0 flex-1">
                        <h5 class="text-body font-semibold leading-snug text-ink">
                            {{ insight.title || "Untitled insight" }}
                        </h5>
                        <p v-if="insight.description" class="mt-0.5 text-data text-ink-muted">
                            {{ insight.description }}
                        </p>

                        <!-- EVIDENCE (collapsed) -->
                        <details v-if="insight.evidence" class="group/evidence mt-1.5">
                            <summary
                                class="inline-flex cursor-pointer list-none items-center gap-1 rounded-[4px] text-caption font-medium text-forest hover:underline [&::-webkit-details-marker]:hidden">
                                <Icon name="chevron-right" :size="14"
                                    class="transition-transform duration-150 group-open/evidence:rotate-90" />
                                Evidence
                            </summary>

                            <div class="mt-2 rounded-control border border-line bg-canvas/70 px-3 py-2.5">

                                <!-- COVERAGE -->
                                <div v-if="insight.type === 'coverage' && insight.evidence.observed_periods !== undefined">
                                    <div class="mb-2 flex items-center justify-between gap-2">
                                        <p class="text-caption tabular-nums text-ink">{{ getCoverageSummary(insight.evidence) }}</p>
                                        <StatusChip :tone="{
                                            Complete: 'success',
                                            'Mostly complete': 'warning',
                                            Incomplete: 'error',
                                        }[getCoverageStatus(insight.evidence).label] || 'neutral'"
                                            :label="getCoverageStatus(insight.evidence).label" />
                                    </div>
                                    <div class="h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar"
                                        :aria-valuenow="Math.round(getCoveragePercentage(insight.evidence))"
                                        aria-valuemin="0" aria-valuemax="100" aria-label="Data coverage">
                                        <div class="h-full rounded-full bg-forest"
                                            :style="{ width: getCoveragePercentage(insight.evidence) + '%' }"></div>
                                    </div>
                                    <div v-if="hasMissingPeriods(insight.evidence)" class="mt-2">
                                        <p class="mb-1 text-caption text-ink-muted">Missing periods</p>
                                        <div class="flex flex-wrap gap-1">
                                            <span v-for="period in insight.evidence.missing_periods" :key="period"
                                                class="rounded-[4px] border border-line bg-surface px-1.5 py-0.5 font-mono text-caption text-ink">
                                                {{ period }}
                                            </span>
                                        </div>
                                    </div>
                                </div>

                                <!-- MULTI-ROW EVIDENCE -->
                                <div v-else-if="getEvidenceRows(insight.evidence).length > 1">
                                    <p class="mb-1 text-caption text-ink-muted">
                                        Supporting data · <span class="tabular-nums">{{ getEvidenceRows(insight.evidence).length }}</span> points
                                    </p>
                                    <dl class="max-h-40 overflow-y-auto text-caption [scrollbar-width:thin]">
                                        <div v-for="(row, rowIndex) in getEvidenceRows(insight.evidence)" :key="rowIndex"
                                            class="flex items-baseline justify-between gap-3 py-0.5">
                                            <dt class="min-w-0 truncate text-ink-muted">{{ getEvidenceLabel(row, insight.evidence) }}</dt>
                                            <dd class="shrink-0 font-medium tabular-nums text-ink">
                                                {{ formatValue(getEvidenceValue(row, insight.evidence)) }}
                                            </dd>
                                        </div>
                                    </dl>
                                </div>

                                <!-- SINGLE ROW EVIDENCE -->
                                <div v-else-if="getEvidenceRows(insight.evidence).length === 1"
                                    class="flex items-baseline justify-between gap-3">
                                    <p class="min-w-0 truncate text-caption text-ink-muted">
                                        {{ getEvidenceLabel(getEvidenceRows(insight.evidence)[0], insight.evidence) }}
                                        <span class="font-mono">· {{ getEvidenceColumn(insight.evidence) }}</span>
                                    </p>
                                    <p class="shrink-0 text-data font-semibold tabular-nums text-ink">
                                        {{ formatEvidenceValue(getEvidenceValue(getEvidenceRows(insight.evidence)[0], insight.evidence)) }}
                                    </p>
                                </div>

                                <!-- GENERIC EVIDENCE FALLBACK -->
                                <pre v-else
                                    class="m-0 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-caption text-ink-muted">{{ JSON.stringify(insight.evidence, null, 2) }}</pre>

                            </div>
                        </details>
                    </div>

                </article>
            </li>
        </ol>

        <p class="flex items-start gap-1.5 border-t border-line/70 px-4 pb-1 pt-2.5 text-caption text-ink-muted">
            <Icon v-if="allEvidenceBacked" name="check-circle" :size="14" class="mt-px text-success" />
            <span>{{ isComputed ? "Calculated directly from the rows in this result" : "Generated from your analysis" }}{{ allEvidenceBacked ? " · evidence-backed" : "" }}</span>
        </p>

    </div>
</template>
