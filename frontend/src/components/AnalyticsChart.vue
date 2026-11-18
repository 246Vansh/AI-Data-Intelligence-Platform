<script setup>
import { useElementSize } from "@vueuse/core";
import { computed, ref, watch } from "vue";
import VChart from "vue-echarts";
import { use } from "echarts/core";

import {
    BarChart,
    LineChart,
    PieChart,
    ScatterChart,
} from "echarts/charts";

import {
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
} from "echarts/components";

import { CanvasRenderer } from "echarts/renderers";

import {
    axisLabelStyle,
    axisLineStyle,
    baseTextStyle,
    dataZoomSliderStyle,
    emphasisShadow,
    getChartTheme,
    legendTextStyle,
    splitLineStyle,
    tooltipStyle,
} from "../services/chartTheme";
import {
    extractCategories,
    formatCompactNumber,
    formatNumber,
    summarizeResult,
} from "../services/chartSummary";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";

use([
    BarChart,
    LineChart,
    PieChart,
    ScatterChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    DataZoomComponent,
    CanvasRenderer,
]);

// =========================================================
// PROPS
// =========================================================

const props = defineProps({
    result: {
        type: Object,
        required: true,
    },
    // Bar charts: color each bar by its rank (darkest = largest value)
    // instead of one flat series color. Presentation only.
    ranked: {
        type: Boolean,
        default: false,
    },
    // Hide the footer line (value count / axes) when the host already
    // shows that context.
    bare: {
        type: Boolean,
        default: false,
    },
});

// Rank of every value, largest first; NULLs get no rank.
function rankColors(values, ramp) {
    const order = values
        .map((value, index) => ({ value, index }))
        .filter((entry) => entry.value !== null)
        .sort((a, b) => b.value - a.value);
    const colors = new Array(values.length).fill(null);
    order.forEach((entry, rank) => {
        colors[entry.index] = ramp[Math.min(rank, ramp.length - 1)];
    });
    return colors;
}

// =========================================================
// BACKEND RESULT
// =========================================================

// Workspace Phase 2: data extraction and the metric summary come from
// services/chartSummary.js (moved there unchanged, and unit-tested), so
// the result header's KPI row and this chart share one implementation.
// The names below are the same ones chartOption has always used.
const summary = computed(() => summarizeResult(props.result));

// ECharts measures its element once, at init. A result that arrives
// while the Analyze tab is hidden (display: none) would init at 0x0
// (console warning). So the chart is created the first time its box
// has a size, and kept from then on (autoresize already ignores 0x0
// resizes when the tab is hidden again).
const chartBox = ref(null);
const { width: boxWidth, height: boxHeight } = useElementSize(chartBox);
const chartReady = ref(false);
watch([boxWidth, boxHeight], ([width, height]) => {
    if (width > 0 && height > 0) chartReady.value = true;
}, { immediate: true });

const rows = computed(() => summary.value.rows);
const visualization = computed(() => summary.value.visualization);
const visualizationType = computed(() => summary.value.visualizationType);
const visualizationTitle = computed(() => visualization.value?.title || "Analysis Result");
const rowCount = computed(() => props.result?.data?.row_count ?? rows.value.length);
const xColumn = computed(() => summary.value.xColumn);
const yColumn = computed(() => summary.value.yColumn);
const hasChartData = computed(() => summary.value.hasChartData);

const chartLabel = computed(() => {
    if (!visualizationType.value) {
        return "Chart";
    }

    return (
        visualizationType.value
            .charAt(0)
            .toUpperCase() +
        visualizationType.value.slice(1)
    );
});

const categories = computed(() => extractCategories(rows.value, xColumn.value));
const numericValues = computed(() => summary.value.numericValues);
const validNumericValues = computed(() => summary.value.validNumericValues);
const rowLimitReached = computed(() => summary.value.rowLimitReached);
const metricLabel = computed(() => summary.value.metricLabel);

function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function formatCategory(value) {
    if (
        value === null ||
        value === undefined
    ) {
        return "Unknown";
    }

    const text = String(value);

    if (text.length <= 18) {
        return text;
    }

    return `${text.slice(0, 17)}…`;
}

// =========================================================
// COMMON ECHARTS STYLES
// =========================================================
//
// Phase 5: presentation (colors, fonts, axes, tooltip) comes from the
// design tokens via services/chartTheme.js. Only presentation keys
// changed in chartOption below; every data key (series data, NULL
// filtering, connectNulls, zoom thresholds, formatters) is unchanged.

// =========================================================
// CHART OPTION
// =========================================================

const chartOption = computed(() => {
    if (!hasChartData.value) {
        return {};
    }

    const type = visualizationType.value;
    const theme = getChartTheme();
    const palette = theme.palette.length ? theme.palette : undefined;

    // =====================================================
    // PIE
    // =====================================================

    if (type === "pie") {
        return {
            animation: true,
            animationDuration: 550,

            color: palette,

            textStyle: baseTextStyle(theme),

            tooltip: {
                ...tooltipStyle(theme),
                trigger: "item",

                formatter(params) {
                    const safeName = escapeHtml(params.name);
                    const safePercent = Number(params.percent) || 0;
                    return `
                        <div style="font-weight:600;margin-bottom:5px;">
                            ${safeName}
                        </div>

                        <div>
                            Value:
                            <strong>
                                ${formatNumber(params.value)}
                            </strong>
                        </div>

                        <div style="margin-top:3px;opacity:.75;">
                            ${safePercent}% of total
                        </div>
                    `;
                },
            },

            legend: {
                type: "scroll",
                bottom: 4,
                left: "center",

                textStyle: legendTextStyle(theme),

                itemWidth: 9,
                itemHeight: 9,
                itemGap: 12,
            },

            series: [
                {
                    type: "pie",

                    radius: ["40%", "68%"],

                    center: ["50%", "46%"],

                    avoidLabelOverlap: true,

                    minAngle: 3,

                    // 2px surface-colored gap between slices.
                    itemStyle: {
                        borderColor: theme.surface || undefined,
                        borderWidth: 2,
                        borderRadius: 4,
                    },

                    label: {
                        color: theme.ink || undefined,
                        fontFamily: theme.fontSans || undefined,
                        fontSize: 11,

                        formatter(params) {
                            if (params.percent < 5) {
                                return "";
                            }

                            return `${formatCategory(
                                params.name
                            )}\n${params.percent}%`;
                        },
                    },

                    labelLine: {
                        length: 10,
                        length2: 8,
                    },

                    emphasis: {
                        scale: true,
                        scaleSize: 6,

                        label: {
                            fontWeight: 700,
                        },

                        itemStyle: {
                            shadowBlur: 18,
                            shadowColor: emphasisShadow(theme),
                        },
                    },

                    // A missing aggregate is not a zero slice.
                    data: categories.value
                        .map((name, index) => ({
                            name,
                            value: numericValues.value[index],
                        }))
                        .filter((item) => item.value !== null),
                },
            ],
        };
    }

    // =====================================================
    // STANDARD CHARTS
    // =====================================================

    const isBar = type === "bar";
    const isLine = type === "line";
    const isScatter = type === "scatter";

    const shouldEnableZoom =
        categories.value.length > 10;

    // Value labels on bars only while they stay legible (few bars);
    // presentation only - the same numbers the tooltip shows.
    const showValueLabels = isBar && categories.value.length <= 12;

    return {
        animation: true,
        animationDuration: 550,

        color: palette,

        textStyle: baseTextStyle(theme),

        tooltip: {
            ...tooltipStyle(theme),

            trigger: isScatter
                ? "item"
                : "axis",

            axisPointer: {
                type: isLine
                    ? "line"
                    : "shadow",
            },

            formatter(params) {
                const item = Array.isArray(params)
                    ? params[0]
                    : params;

                if (!item) {
                    return "";
                }

                const category =
                    item.axisValue ??
                    item.name ??
                    "";

                const value = Array.isArray(
                    item.value
                )
                    ? item.value[
                    item.value.length - 1
                    ]
                    : item.value;

                const safeCategory = escapeHtml(category);
                const safeYColumn = escapeHtml(metricLabel.value);

                return `
                    <div style="font-weight:600;margin-bottom:5px;">
                        ${safeCategory}
                    </div>

                    <div>
                        ${safeYColumn}:
                        <strong>
                            ${formatNumber(value)}
                        </strong>
                    </div>
                `;
            },
        },

        grid: {
            left: "2%",
            right: "2%",
            // Room above the tallest bar for its value label.
            top: showValueLabels ? 30 : 16,

            bottom: shouldEnableZoom
                ? 105
                : categories.value.length > 8
                    ? 82
                    : 62,

            containLabel: true,
        },

        xAxis: {
            type: "category",

            data: categories.value,

            boundaryGap: isBar,

            axisLine: axisLineStyle(theme),

            axisTick: {
                show: false,
            },

            axisLabel: {
                ...axisLabelStyle(theme),
                margin: 12,

                rotate:
                    categories.value.length > 8
                        ? 28
                        : 0,

                formatter(value) {
                    return formatCategory(value);
                },
            },
        },

        yAxis: {
            type: "value",

            axisLine: {
                show: false,
            },

            axisTick: {
                show: false,
            },

            axisLabel: {
                ...axisLabelStyle(theme),

                formatter(value) {
                    return formatCompactNumber(
                        value
                    );
                },
            },

            splitLine: splitLineStyle(theme),
        },

        ...(shouldEnableZoom
            ? {
                dataZoom: [
                    {
                        type: "inside",

                        start: 0,
                        end: 100,
                    },

                    {
                        type: "slider",

                        bottom: 22,
                        height: 16,

                        ...dataZoomSliderStyle(theme),
                    },
                ],
            }
            : {}),

        series: [
            {
                type,

                data: isBar && props.ranked && theme.rankRamp?.length
                    ? (() => {
                        const colors = rankColors(numericValues.value, theme.rankRamp);
                        return numericValues.value.map((value, index) => ({
                            value,
                            itemStyle: colors[index] ? { color: colors[index] } : undefined,
                        }));
                    })()
                    : numericValues.value,

                smooth: isLine,

                connectNulls: false,

                symbol: isLine
                    ? "circle"
                    : undefined,

                // Markers >= 8px; thin 2px lines; 4px rounded bar ends.
                symbolSize: isLine
                    ? 8
                    : isScatter
                        ? 9
                        : undefined,

                barMaxWidth: isBar
                    ? 64
                    : undefined,

                barCategoryGap: isBar ? "28%" : undefined,

                label: showValueLabels
                    ? {
                        show: true,
                        position: "top",
                        distance: 6,
                        color: theme.ink || undefined,
                        fontFamily: theme.fontSans || undefined,
                        fontSize: 12,
                        fontWeight: 600,
                        formatter: (params) => formatCompactNumber(params.value),
                    }
                    : undefined,

                itemStyle: {
                    borderRadius: isBar
                        ? [4, 4, 0, 0]
                        : undefined,
                },

                lineStyle: isLine
                    ? {
                        width: 2,
                    }
                    : undefined,

                areaStyle: isLine
                    ? {
                        opacity: 0.08,
                    }
                    : undefined,

                emphasis: {
                    focus: "series",

                    itemStyle: {
                        shadowBlur: 12,
                        shadowColor: emphasisShadow(theme),
                    },
                },
            },
        ],
    };
});
</script>

<template>
    <!-- Workspace Phase 2: the chart is the drawing surface only. Its
         title, type, result count and the aggregation-aware KPI row
         are rendered by the result header (AnalyticsBuilder, via
         services/chartSummary.js). It fills the height its container
         gives it (min 280px); autoresize follows width and height. -->
    <div class="flex min-h-0 flex-1 flex-col">

        <!-- The chart is absolutely positioned inside the flex-grown box:
             a percentage height would not resolve there, and ECharts
             measures its element once at init (0px = warning + a resize). -->
        <div v-if="hasChartData" ref="chartBox" class="relative min-h-[280px] flex-1"
            role="img" :aria-label="`${chartLabel} chart: ${metricLabel} by ${xColumn}. Switch to Table for the values.`">
            <VChart v-if="chartReady" :option="chartOption" autoresize class="absolute inset-x-1 bottom-0 top-2" />
        </div>

        <EmptyState v-else icon="bar-chart" title="No chart available"
            description="The analysis did not return enough visualization data to render a useful chart." />

        <p v-if="hasChartData && !bare"
            class="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-t border-line px-1 pt-2 text-caption text-ink-muted">
            <span>
                <span class="font-medium tabular-nums text-ink">{{ validNumericValues.length }}</span> numeric values
                <span v-if="rowLimitReached" class="text-warn-ink">(row limit reached - more groups may exist)</span>
            </span>
            <span class="flex items-center gap-1.5">
                <Icon name="arrow-right" :size="14" /> X
                <span class="font-mono text-ink">{{ xColumn }}</span>
            </span>
            <span class="flex items-center gap-1.5">
                <Icon name="arrow-up" :size="14" /> Y
                <span class="font-mono text-ink">{{ yColumn }}</span>
            </span>
        </p>

    </div>
</template>
