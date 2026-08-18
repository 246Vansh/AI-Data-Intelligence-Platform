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
    TitleComponent,
} from "echarts/components";

import {
    CanvasRenderer,
} from "echarts/renderers";


use([
    BarChart,
    LineChart,
    PieChart,
    ScatterChart,
    GridComponent,
    TooltipComponent,
    LegendComponent,
    TitleComponent,
    CanvasRenderer,
]);


const props = defineProps({
    result: {
        type: Object,
        required: true,
    },
});


const chartOption = computed(() => {

    const rows =
        props.result?.data?.rows || [];

    const visualization =
        props.result?.visualization;


    if (
        !rows.length ||
        !visualization
    ) {
        return {};
    }


    const xColumn =
        visualization.encoding?.x;

    const yColumn =
        visualization.encoding?.y;


    if (!xColumn || !yColumn) {
        return {};
    }


    const categories =
        rows.map(
            row => row[xColumn]
        );


    const values =
        rows.map(
            row => row[yColumn]
        );


    /* =========================================
       Pie Chart
    ========================================= */

    if (
        visualization.type === "pie"
    ) {

        return {

            animation: true,

            animationDuration: 700,

            title: {
                text: visualization.title,
                left: "center",
                top: 10,

                textStyle: {
                    fontSize: 17,
                    fontWeight: 700,
                    color: "#172033",
                },
            },

            tooltip: {
                trigger: "item",

                backgroundColor: "rgba(23, 32, 51, 0.94)",

                borderWidth: 0,

                textStyle: {
                    color: "#ffffff",
                    fontSize: 12,
                },

                formatter: "{b}<br/>Value: {c} ({d}%)",
            },

            legend: {
                type: "scroll",

                bottom: 4,

                left: "center",

                textStyle: {
                    color: "#667085",
                    fontSize: 11,
                },

                itemWidth: 10,
                itemHeight: 10,
            },

            series: [
                {
                    type: "pie",

                    radius: [
                        "38%",
                        "68%",
                    ],

                    center: [
                        "50%",
                        "48%",
                    ],

                    avoidLabelOverlap: true,

                    itemStyle: {
                        borderColor: "#ffffff",
                        borderWidth: 3,
                        borderRadius: 6,
                    },

                    label: {
                        color: "#475467",
                        fontSize: 11,
                    },

                    emphasis: {
                        scale: true,
                        scaleSize: 5,

                        itemStyle: {
                            shadowBlur: 18,
                            shadowColor:
                                "rgba(15, 23, 42, 0.16)",
                        },
                    },

                    data: rows.map(
                        row => ({
                            name: row[xColumn],
                            value: row[yColumn],
                        })
                    ),
                },
            ],
        };
    }


    /* =========================================
       Standard Charts
    ========================================= */

    const isBar =
        visualization.type === "bar";

    const isLine =
        visualization.type === "line";

    const isScatter =
        visualization.type === "scatter";


    return {

        animation: true,

        animationDuration: 700,

        title: {
            text: visualization.title,

            left: 0,

            top: 0,

            textStyle: {
                fontSize: 17,
                fontWeight: 700,
                color: "#172033",
            },
        },


        tooltip: {

            trigger:
                isScatter
                    ? "item"
                    : "axis",

            backgroundColor:
                "rgba(23, 32, 51, 0.94)",

            borderWidth: 0,

            textStyle: {
                color: "#ffffff",
                fontSize: 12,
            },

            axisPointer: {
                type:
                    isLine
                        ? "line"
                        : "shadow",
            },
        },


        grid: {

            left: "2%",

            right: "2%",

            top: 55,

            bottom: 65,

            containLabel: true,
        },


        xAxis: {

            type: "category",

            data: categories,

            boundaryGap:
                isBar,

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
                    categories.length > 7
                        ? 25
                        : 0,
            },
        },


        yAxis: {

            type: "value",

            splitLine: {
                lineStyle: {
                    color: "#edf0f5",

                    type: "dashed",
                },
            },

            axisLine: {
                show: false,
            },

            axisTick: {
                show: false,
            },

            axisLabel: {
                color: "#667085",

                fontSize: 11,
            },
        },


        series: [

            {

                type:
                    visualization.type,

                data: values,

                smooth:
                    isLine,

                symbol:
                    isLine
                        ? "circle"
                        : undefined,

                symbolSize:
                    isLine
                        ? 7
                        : undefined,

                barMaxWidth:
                    isBar
                        ? 42
                        : undefined,

                itemStyle: {

                    borderRadius:
                        isBar
                            ? [7, 7, 0, 0]
                            : undefined,
                },

                lineStyle:
                    isLine
                        ? {
                            width: 3,
                        }
                        : undefined,

                areaStyle:
                    isLine
                        ? {
                            opacity: 0.08,
                        }
                        : undefined,

                emphasis: {

                    focus: "series",

                    itemStyle: {
                        shadowBlur: 10,
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

    <section class="chart-container">

        <div class="chart-toolbar">

            <div class="chart-info">

                <span class="chart-indicator"></span>

                <span>
                    {{ result?.visualization?.type || "Chart" }}
                </span>

            </div>

            <span class="data-count">
                {{ result?.data?.row_count || 0 }} results
            </span>

        </div>


        <div class="chart">

            <VChart :option="chartOption" autoresize />

        </div>

    </section>

</template>


<style scoped>
.chart-container {
    width: 100%;

    margin-top: 4px;

    padding: 20px;

    border: 1px solid #edf0f5;

    border-radius: 16px;

    background: #ffffff;

    box-sizing: border-box;
}


/* =========================
   Toolbar
========================= */

.chart-toolbar {
    display: flex;

    align-items: center;

    justify-content: space-between;

    margin-bottom: 4px;
}


.chart-info {
    display: flex;

    align-items: center;

    gap: 7px;

    color: #667085;

    font-size: 11px;

    font-weight: 650;

    text-transform: capitalize;
}


.chart-indicator {
    width: 7px;

    height: 7px;

    border-radius: 50%;

    background: #7c3aed;

    box-shadow:
        0 0 0 4px rgba(124,
            58,
            237,
            0.10);
}


.data-count {
    padding: 5px 9px;

    border-radius: 7px;

    background: #f8f7ff;

    color: #7c3aed;

    font-size: 10px;

    font-weight: 650;
}


/* =========================
   ECharts
========================= */

.chart {
    width: 100%;

    height: 440px;
}


/* =========================
   Responsive
========================= */

@media (max-width: 700px) {

    .chart-container {
        padding: 14px;
    }

    .chart {
        height: 360px;
    }

}

@media (max-width: 450px) {

    .chart {
        height: 300px;
    }

}
</style>