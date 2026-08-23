<script setup>
import { computed } from "vue";
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
});

// =========================================================
// BACKEND RESULT
// =========================================================

const rows = computed(() => {
    return Array.isArray(props.result?.data?.rows)
        ? props.result.data.rows
        : [];
});

const visualization = computed(() => {
    return props.result?.visualization || null;
});

const visualizationType = computed(() => {
    return visualization.value?.type || null;
});

const visualizationTitle = computed(() => {
    return (
        visualization.value?.title ||
        "Analysis Result"
    );
});

const rowCount = computed(() => {
    return (
        props.result?.data?.row_count ??
        rows.value.length
    );
});

const encoding = computed(() => {
    return visualization.value?.encoding || {};
});

const xColumn = computed(() => {
    return encoding.value?.x || null;
});

const yColumn = computed(() => {
    return encoding.value?.y || null;
});

// =========================================================
// CHART STATE
// =========================================================

const supportedChartTypes = [
    "bar",
    "line",
    "pie",
    "scatter",
];

const isSupportedChart = computed(() => {
    return supportedChartTypes.includes(
        visualizationType.value
    );
});

const hasChartData = computed(() => {
    return (
        rows.value.length > 0 &&
        !!visualization.value &&
        !!xColumn.value &&
        !!yColumn.value &&
        isSupportedChart.value
    );
});

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

// =========================================================
// DATA EXTRACTION
// =========================================================

const categories = computed(() => {
    return rows.value.map((row) => {
        const value = row?.[xColumn.value];

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return "Unknown";
        }

        return String(value);
    });
});

const numericValues = computed(() => {
    return rows.value.map((row) => {
        const value = row?.[yColumn.value];

        if (
            value === null ||
            value === undefined ||
            value === ""
        ) {
            return null;
        }

        const number = Number(value);

        return Number.isFinite(number)
            ? number
            : null;
    });
});

const validNumericValues = computed(() => {
    return numericValues.value.filter(
        (value) =>
            value !== null &&
            Number.isFinite(value)
    );
});

// =========================================================
// METRIC SUMMARY
// =========================================================

const totalValue = computed(() => {
    return validNumericValues.value.reduce(
        (sum, value) => sum + value,
        0
    );
});

const averageValue = computed(() => {
    if (!validNumericValues.value.length) {
        return null;
    }

    return (
        totalValue.value /
        validNumericValues.value.length
    );
});

const minimumValue = computed(() => {
    if (!validNumericValues.value.length) {
        return null;
    }

    return Math.min(
        ...validNumericValues.value
    );
});

const maximumValue = computed(() => {
    if (!validNumericValues.value.length) {
        return null;
    }

    return Math.max(
        ...validNumericValues.value
    );
});

// =========================================================
// FORMATTERS
// =========================================================

function formatNumber(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return String(value);
    }

    return new Intl.NumberFormat("en-US", {
        maximumFractionDigits: 2,
    }).format(number);
}

function formatCompactNumber(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return String(value);
    }

    return new Intl.NumberFormat("en-US", {
        notation: "compact",
        maximumFractionDigits: 1,
    }).format(number);
}

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

const baseTextStyle = {
    fontFamily:
        "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
};

const tooltipStyle = {
    backgroundColor: "rgba(23, 32, 51, 0.97)",
    borderWidth: 0,
    borderRadius: 10,
    padding: [10, 12],
    textStyle: {
        color: "#ffffff",
        fontSize: 12,
    },
    extraCssText:
        "box-shadow: 0 10px 30px rgba(15,23,42,0.16);",
};

// =========================================================
// CHART OPTION
// =========================================================

const chartOption = computed(() => {
    if (!hasChartData.value) {
        return {};
    }

    const type = visualizationType.value;

    // =====================================================
    // PIE
    // =====================================================

    if (type === "pie") {
        return {
            animation: true,
            animationDuration: 550,

            textStyle: baseTextStyle,

            tooltip: {
                ...tooltipStyle,
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

                textStyle: {
                    color: "#667085",
                    fontSize: 11,
                },

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

                    itemStyle: {
                        borderColor: "#ffffff",
                        borderWidth: 3,
                        borderRadius: 6,
                    },

                    label: {
                        color: "#475467",
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
                            shadowColor:
                                "rgba(15, 23, 42, 0.16)",
                        },
                    },

                    data: rows.value.map((row) => ({
                        name:
                            row?.[xColumn.value] ??
                            "Unknown",

                        value:
                            Number(
                                row?.[yColumn.value]
                            ) || 0,
                    })),
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

    const chartCategories =
        categories.value.map(formatCategory);

    const shouldEnableZoom =
        categories.value.length > 10;

    return {
        animation: true,
        animationDuration: 550,

        textStyle: baseTextStyle,

        tooltip: {
            ...tooltipStyle,

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
                const safeYColumn = escapeHtml(yColumn.value);

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
            top: 55,

            bottom: shouldEnableZoom
                ? 105
                : categories.value.length > 8
                    ? 82
                    : 62,

            containLabel: true,
        },

        xAxis: {
            type: "category",

            data: chartCategories,

            boundaryGap: isBar,

            axisLine: {
                lineStyle: {
                    color: "#e4e7ec",
                },
            },

            axisTick: {
                show: false,
            },

            axisLabel: {
                color: "#667085",
                fontSize: 11,
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
                color: "#667085",
                fontSize: 11,

                formatter(value) {
                    return formatCompactNumber(
                        value
                    );
                },
            },

            splitLine: {
                lineStyle: {
                    color: "#edf0f5",
                    type: "dashed",
                },
            },
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

                        borderColor:
                            "#e4e7ec",

                        backgroundColor:
                            "#f8fafc",

                        fillerColor:
                            "rgba(124,58,237,0.12)",

                        handleStyle: {
                            color: "#7c3aed",
                        },

                        textStyle: {
                            color: "#667085",
                            fontSize: 10,
                        },
                    },
                ],
            }
            : {}),

        series: [
            {
                type,

                data: numericValues.value,

                smooth: isLine,

                connectNulls: false,

                symbol: isLine
                    ? "circle"
                    : undefined,

                symbolSize: isLine
                    ? 7
                    : isScatter
                        ? 9
                        : undefined,

                barMaxWidth: isBar
                    ? 42
                    : undefined,

                itemStyle: {
                    borderRadius: isBar
                        ? [7, 7, 0, 0]
                        : undefined,
                },

                lineStyle: isLine
                    ? {
                        width: 3,
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
                        shadowColor:
                            "rgba(79, 70, 229, 0.16)",
                    },
                },
            },
        ],
    };
});
</script>

<template>
    <section
        class="mt-1 w-full overflow-hidden rounded-2xl border border-[#e9eaf0] bg-white shadow-[0_5px_15px_rgba(15,23,42,0.025),0_12px_28px_rgba(15,23,42,0.035)]">
        <!-- =================================================
             HEADER
        ================================================== -->

        <div
            class="flex items-start justify-between gap-4 border-b border-[#edf0f5] bg-gradient-to-b from-white to-[#fcfcfe] px-5 py-4 max-[650px]:flex-col">
            <div class="min-w-0">
                <div class="mb-1.5 flex items-center gap-2">
                    <span
                        class="h-2 w-2 shrink-0 rounded-full bg-[#7c3aed] shadow-[0_0_0_4px_rgba(124,58,237,0.10)]"></span>

                    <span class="text-[10px] font-bold uppercase tracking-[0.8px] text-[#7c3aed]">
                        {{ chartLabel }}
                    </span>
                </div>

                <h3 class="m-0 text-[17px] font-bold tracking-[-0.2px] text-[#172033]">
                    {{ visualizationTitle }}
                </h3>

                <p v-if="hasChartData" class="mt-1 text-[11px] text-[#98a2b3]">
                    {{ yColumn }} measured across
                    {{ xColumn }}
                </p>
            </div>

            <div class="flex shrink-0 items-center gap-2">
                <span class="rounded-lg bg-[#f5f3ff] px-2.5 py-1.5 text-[10px] font-bold text-[#6d28d9]">
                    {{ rowCount }} results
                </span>
            </div>
        </div>

        <!-- =================================================
             METRIC SUMMARY
        ================================================== -->

        <div v-if="
            hasChartData &&
            visualizationType !== 'pie' &&
            validNumericValues.length
        " class="grid grid-cols-4 border-b border-[#edf0f5] max-[700px]:grid-cols-2">
            <!-- Total -->
            <div class="border-r border-[#edf0f5] px-4 py-3 max-[700px]:border-b">
                <p class="m-0 text-[10px] font-semibold uppercase tracking-[0.5px] text-[#98a2b3]">
                    Total
                </p>

                <p class="mt-1 m-0 truncate text-[17px] font-bold text-[#172033]" :title="formatNumber(totalValue)">
                    {{ formatCompactNumber(totalValue) }}
                </p>
            </div>

            <!-- Average -->
            <div class="border-r border-[#edf0f5] px-4 py-3 max-[700px]:border-b max-[700px]:border-r-0">
                <p class="m-0 text-[10px] font-semibold uppercase tracking-[0.5px] text-[#98a2b3]">
                    Average
                </p>

                <p class="mt-1 m-0 truncate text-[17px] font-bold text-[#172033]" :title="formatNumber(averageValue)">
                    {{ formatCompactNumber(averageValue) }}
                </p>
            </div>

            <!-- Minimum -->
            <div class="border-r border-[#edf0f5] px-4 py-3 max-[700px]:border-r">
                <p class="m-0 text-[10px] font-semibold uppercase tracking-[0.5px] text-[#98a2b3]">
                    Minimum
                </p>

                <p class="mt-1 m-0 truncate text-[17px] font-bold text-[#172033]" :title="formatNumber(minimumValue)">
                    {{ formatCompactNumber(minimumValue) }}
                </p>
            </div>

            <!-- Maximum -->
            <div class="px-4 py-3">
                <p class="m-0 text-[10px] font-semibold uppercase tracking-[0.5px] text-[#98a2b3]">
                    Maximum
                </p>

                <p class="mt-1 m-0 truncate text-[17px] font-bold text-[#172033]" :title="formatNumber(maximumValue)">
                    {{ formatCompactNumber(maximumValue) }}
                </p>
            </div>
        </div>

        <!-- =================================================
             CHART
        ================================================== -->

        <div v-if="hasChartData" class="h-[440px] w-full px-2 pb-2 pt-1 max-[700px]:h-[390px] max-[450px]:h-[330px]">
            <VChart :option="chartOption" autoresize class="h-full w-full" />
        </div>

        <!-- =================================================
             EMPTY / INVALID STATE
        ================================================== -->

        <div v-else class="flex min-h-[300px] items-center justify-center px-6 py-12">
            <div class="max-w-sm text-center">
                <div
                    class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-[#f5f3ff] text-[#7c3aed]">
                    <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                        <path d="M4 19V5" stroke-linecap="round" />

                        <path d="M4 19h16" stroke-linecap="round" />

                        <path d="m7 15 3-4 3 2 4-6" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                </div>

                <h3 class="m-0 text-sm font-bold text-[#172033]">
                    No chart available
                </h3>

                <p class="mt-2 text-xs leading-5 text-[#98a2b3]">
                    The analysis did not return enough
                    visualization data to render a useful
                    chart.
                </p>
            </div>
        </div>

        <!-- =================================================
             FOOTER
        ================================================== -->

        <div v-if="hasChartData"
            class="flex items-center justify-between gap-4 border-t border-[#edf0f5] bg-[#fcfcfd] px-5 py-2.5 text-[10px] text-[#98a2b3] max-[500px]:items-start max-[500px]:flex-col">
            <span>
                Showing
                <strong class="font-semibold text-[#667085]">
                    {{ validNumericValues.length }}
                </strong>
                numeric values
            </span>

            <div class="flex items-center gap-4 max-[500px]:flex-col max-[500px]:items-start max-[500px]:gap-1">
                <span>
                    X:
                    <strong class="font-semibold text-[#667085]">
                        {{ xColumn }}
                    </strong>
                </span>

                <span>
                    Y:
                    <strong class="font-semibold text-[#667085]">
                        {{ yColumn }}
                    </strong>
                </span>
            </div>
        </div>
    </section>
</template>