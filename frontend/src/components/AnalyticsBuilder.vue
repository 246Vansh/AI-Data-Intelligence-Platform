<script setup>
import { computed, onMounted, ref } from "vue";

import AnalyticsInsights from "./AnalyticsInsights.vue";
import AnalyticsChart from "./AnalyticsChart.vue";

import {
    analyzeDataset,
    getDatasetMetadata,
    getApiErrorMessage,
} from "../services/api";

// =========================================================
// STATE
// =========================================================

const question = ref("");

const loading = ref(false);
const metadataLoading = ref(false);

const error = ref(null);
const result = ref(null);
const metadataError = ref(null);

const metadata = ref(null);

// =========================================================
// DATASET METADATA
// =========================================================

const columns = computed(() => {
    const metadataColumns = metadata.value?.columns;

    if (!metadataColumns || typeof metadataColumns !== "object") {
        return {};
    }

    return metadataColumns;
});

const columnEntries = computed(() => {
    return Object.entries(columns.value);
});

const metricColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) => info?.role === "metric")
        .map(([name]) => name);
});

const dimensionColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) =>
            ["dimension", "categorical"].includes(info?.role),
        )
        .map(([name]) => name);
});

const timeColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) => info?.role === "time")
        .map(([name]) => name);
});

// =========================================================
// EXAMPLE QUESTION GENERATION
// =========================================================

const exampleQuestions = computed(() => {
    const examples = [];

    const metric = metricColumns.value[0];
    const secondMetric = metricColumns.value[1];

    const dimension = dimensionColumns.value[0];
    const secondDimension = dimensionColumns.value[1];

    const timeColumn = timeColumns.value[0];

    // -----------------------------------------------------
    // Time-based examples
    // -----------------------------------------------------

    if (timeColumn && metric) {
        examples.push(`Show me the monthly trend of ${metric}.`);
        examples.push(`Show me the yearly trend of ${metric}.`);
    }

    // -----------------------------------------------------
    // Dimension + metric examples
    // -----------------------------------------------------

    if (dimension && metric) {
        examples.push(
            `Show the top 5 ${dimension} by total ${metric}.`,
        );

        examples.push(
            `Show the average ${metric} by ${dimension}.`,
        );
    }

    // -----------------------------------------------------
    // Second dimension
    // -----------------------------------------------------

    if (
        secondDimension &&
        metric &&
        secondDimension !== dimension
    ) {
        examples.push(
            `Show the top 5 ${secondDimension} by average ${metric}.`,
        );
    }

    // -----------------------------------------------------
    // Second metric
    // -----------------------------------------------------

    if (
        secondMetric &&
        dimension &&
        secondMetric !== metric
    ) {
        examples.push(
            `Show the average ${secondMetric} by ${dimension}.`,
        );
    }

    // -----------------------------------------------------
    // Fallback
    // -----------------------------------------------------

    if (!examples.length && metric) {
        examples.push(`Show the total ${metric}.`);
        examples.push(`Show the average ${metric}.`);
    }

    if (!examples.length && dimension) {
        examples.push(
            `Show the distribution of ${dimension}.`,
        );
    }

    return [...new Set(examples)].slice(0, 5);
});

// =========================================================
// CELL FORMATTING
// =========================================================

function formatCell(value) {
    if (value === null || value === undefined) {
        return "—";
    }

    if (typeof value === "number") {
        if (Number.isInteger(value)) {
            return value.toLocaleString("en-IN");
        }

        return value.toLocaleString("en-IN", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    return value;
}

// =========================================================
// LOAD DATASET METADATA
// =========================================================

async function loadMetadata() {
    try {
        metadataLoading.value = true;
        metadataError.value = null;

        const response = await getDatasetMetadata();

        metadata.value = response;
    } catch (err) {
        console.error(
            "Failed to load dataset metadata:",
            err,
        );

        metadataError.value =
            getApiErrorMessage(err) ||
            "Unable to load dataset metadata.";
    } finally {
        metadataLoading.value = false;
    }
}

// =========================================================
// ANALYZE
// =========================================================

async function analyze() {
    const trimmedQuestion = question.value.trim();

    if (!trimmedQuestion || loading.value) {
        return;
    }

    try {
        loading.value = true;
        error.value = null;
        result.value = null;

        const response =
            await analyzeDataset(trimmedQuestion);

        if (!response?.success) {
            error.value =
                response?.error?.message ||
                response?.error ||
                "Unable to analyze the dataset.";

            return;
        }

        result.value = response;
    } catch (err) {
        console.error(
            "Analysis request failed:",
            err,
        );

        error.value =
            getApiErrorMessage(err) ||
            "Unable to analyze dataset.";
    } finally {
        loading.value = false;
    }
}

// =========================================================
// EXAMPLES
// =========================================================

function useExample(example) {
    if (loading.value) {
        return;
    }

    question.value = example;
    error.value = null;
    result.value = null;
}

function clearAnalysis() {
    question.value = "";
    error.value = null;
    result.value = null;
}

function handleKeydown(event) {
    if (
        event.ctrlKey &&
        event.key === "Enter"
    ) {
        event.preventDefault();
        analyze();
    }
}

// =========================================================
// INITIALIZE
// =========================================================

onMounted(() => {
    loadMetadata();
});
</script>

<template>
    <section class="w-full">

        <!-- =====================================================
             ASK YOUR DATA
        ====================================================== -->

        <div
            class="relative mt-10 overflow-hidden rounded-[24px] border border-violet-200/70 bg-gradient-to-br from-white via-violet-50/40 to-indigo-50/70 p-7 shadow-[0_8px_25px_rgba(79,70,229,0.07),0_25px_60px_rgba(124,58,237,0.08)] max-[700px]:p-5">

            <!-- Decorative background -->

            <div
                class="pointer-events-none absolute -right-20 -top-24 h-64 w-64 rounded-full bg-violet-300/20 blur-3xl">
            </div>

            <div
                class="pointer-events-none absolute -bottom-24 -left-20 h-64 w-64 rounded-full bg-blue-300/20 blur-3xl">
            </div>

            <div
                class="pointer-events-none absolute right-1/3 top-1/2 h-32 w-32 rounded-full bg-fuchsia-300/10 blur-3xl">
            </div>

            <div class="relative z-10">

                <!-- Header -->

                <div
                    class="mb-[26px] flex items-center justify-between gap-5 max-[700px]:flex-col max-[700px]:items-start">

                    <div class="flex items-center gap-[13px]">

                        <div
                            class="relative flex h-[46px] w-[46px] shrink-0 items-center justify-center rounded-[14px] bg-gradient-to-br from-violet-600 via-purple-600 to-indigo-600 text-white shadow-[0_8px_20px_rgba(124,58,237,0.28)]">

                            <div class="absolute inset-0 rounded-[14px] bg-white/10">
                            </div>

                            <svg class="relative h-[23px] w-[23px]" viewBox="0 0 24 24" fill="none"
                                stroke="currentColor" stroke-width="2">

                                <path
                                    d="M21 11.5a8.38 8.38 0 0 1-9 8.3 8.5 8.5 0 0 1-3.7-.8L3 20l1.3-4.2A8.4 8.4 0 1 1 21 11.5Z" />

                                <path d="M8 12h.01M12 12h.01M16 12h.01" />

                            </svg>

                        </div>

                        <div>

                            <div class="flex items-center gap-2">

                                <h2 class="m-0 text-[21px] font-bold tracking-[-0.4px] text-slate-900">

                                    Ask Your Data

                                </h2>

                                <span
                                    class="rounded-full bg-gradient-to-r from-violet-100 to-indigo-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.4px] text-violet-700">

                                    AI

                                </span>

                            </div>

                            <p class="mt-1 text-[13px] leading-normal text-slate-500">

                                Ask a question in natural language
                                and let AI analyze your dataset.

                            </p>

                        </div>

                    </div>

                    <div
                        class="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-violet-200 bg-gradient-to-r from-violet-100 to-indigo-100 px-[12px] py-[7px] text-xs font-bold text-violet-700 shadow-sm max-[700px]:self-start">

                        <span class="animate-pulse text-sm text-violet-600">
                            ✦
                        </span>

                        AI Powered

                    </div>

                </div>

                <!-- Metadata loading -->

                <div v-if="metadataLoading"
                    class="mb-4 flex items-center gap-2 rounded-xl border border-blue-200 bg-gradient-to-r from-blue-50 to-violet-50 px-4 py-3 text-xs font-medium text-blue-700 shadow-sm">

                    <span class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-blue-200 border-t-violet-600">
                    </span>

                    Understanding your dataset...

                </div>

                <!-- Metadata error -->

                <div v-if="metadataError"
                    class="mb-4 flex items-center gap-3 rounded-xl border border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50 px-4 py-3 text-xs font-medium text-amber-700 shadow-sm">

                    <span
                        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-amber-100 font-bold text-amber-600">
                        !
                    </span>

                    {{ metadataError }}

                </div>

                <!-- Question -->

                <div class="flex flex-col gap-[9px]">

                    <label for="question" class="flex items-center gap-2 text-[13px] font-bold text-slate-700">

                        <span class="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-violet-500 to-indigo-500">
                        </span>

                        What do you want to know?

                    </label>

                    <div class="relative">

                        <textarea id="question" v-model="question" rows="4" :disabled="loading"
                            placeholder="Ask a question about your uploaded dataset..." @keydown="handleKeydown"
                            class="box-border min-h-[130px] w-full resize-y rounded-[16px] border border-violet-200 bg-white/90 px-[17px] py-[17px] pr-12 text-sm leading-[1.6] text-slate-900 shadow-[0_4px_15px_rgba(79,70,229,0.04)] backdrop-blur-sm transition duration-200 placeholder:text-slate-400 hover:border-violet-300 focus:border-violet-500 focus:outline-none focus:ring-4 focus:ring-violet-500/10 disabled:cursor-wait disabled:bg-slate-50">
                        </textarea>

                        <div class="pointer-events-none absolute bottom-4 right-4 text-xl text-violet-500">

                            <span class="animate-pulse">
                                ✦
                            </span>

                        </div>

                    </div>

                    <!-- Example Questions -->

                    <div v-if="exampleQuestions.length" class="mt-2">

                        <div
                            class="mb-2 flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.45px] text-slate-400">

                            <span class="h-1 w-5 rounded-full bg-gradient-to-r from-violet-500 to-indigo-500">
                            </span>

                            Try an example

                        </div>

                        <div class="flex flex-wrap gap-2">

                            <button v-for="(example, index) in exampleQuestions" :key="example" type="button"
                                :disabled="loading" @click="useExample(example)"
                                class="group rounded-full border px-3 py-[7px] text-[11px] font-semibold transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-50"
                                :class="[
                                    index % 4 === 0
                                        ? 'border-violet-200 bg-violet-50 text-violet-700 hover:border-violet-400 hover:bg-violet-100'
                                        : '',
                                    index % 4 === 1
                                        ? 'border-blue-200 bg-blue-50 text-blue-700 hover:border-blue-400 hover:bg-blue-100'
                                        : '',
                                    index % 4 === 2
                                        ? 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 hover:border-fuchsia-400 hover:bg-fuchsia-100'
                                        : '',
                                    index % 4 === 3
                                        ? 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:border-indigo-400 hover:bg-indigo-100'
                                        : '',
                                ]">

                                <span class="mr-1 opacity-60 transition group-hover:opacity-100">
                                    ✦
                                </span>

                                {{ example }}

                            </button>

                        </div>

                    </div>

                    <!-- Footer -->

                    <div
                        class="mt-[8px] flex items-center justify-between gap-[15px] max-[700px]:flex-col max-[700px]:items-start">

                        <span class="text-[11px] text-slate-400">

                            Press

                            <kbd
                                class="mx-0.5 inline-block rounded-[5px] border border-slate-200 border-b-2 bg-white px-[5px] py-0.5 text-[10px] font-semibold text-slate-600 shadow-sm">
                                Ctrl
                            </kbd>

                            +

                            <kbd
                                class="mx-0.5 inline-block rounded-[5px] border border-slate-200 border-b-2 bg-white px-[5px] py-0.5 text-[10px] font-semibold text-slate-600 shadow-sm">
                                Enter
                            </kbd>

                            to analyze

                        </span>

                        <div class="flex items-center gap-2 max-[700px]:w-full">

                            <!-- Clear -->

                            <button v-if="question || result" type="button" :disabled="loading" @click="clearAnalysis"
                                class="rounded-[11px] border border-slate-200 bg-white px-[14px] py-3 text-[13px] font-semibold text-slate-600 shadow-sm transition-all duration-200 hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50">

                                Clear

                            </button>

                            <!-- Analyze -->

                            <button type="button" :disabled="loading || !question.trim()" @click="analyze"
                                class="group flex min-w-[155px] items-center gap-[9px] rounded-[11px] border-0 bg-gradient-to-r from-violet-600 via-purple-600 to-indigo-600 px-[17px] py-3 text-[13px] font-bold text-white shadow-[0_8px_20px_rgba(109,40,217,0.28)] transition-all duration-200 hover:-translate-y-0.5 hover:from-violet-700 hover:via-purple-700 hover:to-indigo-700 hover:shadow-[0_14px_28px_rgba(99,102,241,0.35)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none max-[700px]:flex-1 max-[700px]:justify-center">

                                <span v-if="loading"
                                    class="h-[15px] w-[15px] animate-spin rounded-full border-2 border-white/40 border-t-white">
                                </span>

                                <svg v-else
                                    class="h-[18px] w-[18px] transition-transform duration-200 group-hover:rotate-12"
                                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">

                                    <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />

                                    <path d="M19 16v5M21.5 18.5h-5" />

                                </svg>

                                <span>
                                    {{
                                        loading
                                            ? "Analyzing..."
                                            : "Analyze Data"
                                    }}
                                </span>

                                <span v-if="!loading"
                                    class="ml-auto text-[17px] transition-transform duration-200 group-hover:translate-x-1">
                                    →
                                </span>

                            </button>

                        </div>

                    </div>

                </div>

            </div>
        </div>

        <!-- =====================================================
             ANALYSIS LOADING
        ====================================================== -->

        <div v-if="loading"
            class="relative mt-[18px] overflow-hidden rounded-[16px] border border-violet-200 bg-gradient-to-r from-violet-50 via-white to-indigo-50 px-5 py-4 shadow-[0_8px_25px_rgba(99,102,241,0.08)]">

            <div class="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-violet-500 via-purple-500 to-indigo-500">
            </div>

            <div class="flex items-center gap-4">

                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-100 to-indigo-100">

                    <span class="h-4 w-4 animate-spin rounded-full border-2 border-violet-200 border-t-violet-600">
                    </span>

                </div>

                <div>

                    <strong class="block text-[13px] font-bold text-violet-900">
                        Analyzing your question
                    </strong>

                    <p class="mt-0.5 text-[11px] text-slate-500">
                        Planning the analysis and preparing
                        your results...
                    </p>

                </div>

            </div>

        </div>

        <!-- =====================================================
             ERROR
        ====================================================== -->

        <div v-if="error"
            class="relative mt-[18px] flex items-start gap-[13px] overflow-hidden rounded-[16px] border border-red-200 bg-gradient-to-r from-red-50 via-white to-orange-50 px-[18px] py-4 shadow-[0_6px_20px_rgba(239,68,68,0.07)]">

            <div class="absolute inset-y-0 left-0 w-1 bg-gradient-to-b from-red-500 to-orange-500">
            </div>

            <div
                class="flex h-[36px] w-[36px] shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-red-100 to-orange-100 font-bold text-red-600">

                !

            </div>

            <div class="min-w-0">

                <strong class="mb-[3px] block text-[13px] font-bold text-red-800">
                    Analysis failed
                </strong>

                <p class="m-0 text-xs leading-5 text-red-700">
                    {{ error }}
                </p>

                <button type="button" @click="analyze" :disabled="loading || !question.trim()"
                    class="mt-3 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-[11px] font-bold text-red-700 shadow-sm transition hover:border-red-300 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50">

                    Try Again

                </button>

            </div>

        </div>

        <!-- =====================================================
             RESULT
        ====================================================== -->

        <div v-if="result"
            class="relative mt-6 overflow-hidden rounded-[22px] border border-indigo-100 bg-gradient-to-br from-white via-white to-indigo-50/40 p-6 shadow-[0_8px_25px_rgba(15,23,42,0.05),0_20px_50px_rgba(79,70,229,0.06)] max-[700px]:mt-[18px] max-[700px]:p-4">

            <!-- Result decorative glow -->

            <div
                class="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-emerald-300/10 blur-3xl">
            </div>

            <div class="relative z-10">

                <!-- Result Header -->

                <div
                    class="mb-[22px] flex items-center justify-between gap-5 max-[700px]:flex-col max-[700px]:items-start">

                    <div class="flex items-start gap-3">

                        <div
                            class="flex h-[42px] w-[42px] shrink-0 items-center justify-center rounded-[12px] bg-gradient-to-br from-emerald-400 to-teal-500 text-lg font-bold text-white shadow-[0_7px_18px_rgba(16,185,129,0.22)]">

                            ✓

                        </div>

                        <div>

                            <span
                                class="mb-[3px] block text-[10px] font-bold uppercase tracking-[0.6px] text-emerald-600">
                                Analysis Result
                            </span>

                            <h3 class="m-0 text-[19px] font-bold tracking-[-0.25px] text-slate-900">

                                {{
                                    result.visualization?.title ||
                                    "Analysis completed"
                                }}

                            </h3>

                            <p class="mt-1 text-xs text-slate-400">

                                {{
                                    result.data?.row_count ??
                                    result.data?.rows?.length ??
                                    0
                                }}

                                results returned.

                            </p>

                        </div>

                    </div>

                    <div
                        class="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-emerald-200 bg-gradient-to-r from-emerald-50 to-teal-50 px-[12px] py-[7px] text-[11px] font-bold text-emerald-700 shadow-sm max-[700px]:self-start">

                        <span class="text-emerald-500">
                            ●
                        </span>

                        Analysis Complete

                    </div>

                </div>

                <!-- AI Insights -->

                <AnalyticsInsights v-if="result.insights?.insights?.length" :result="result" />

                <!-- Chart -->

                <div v-if="
                    result.visualization &&
                    result.visualization.type !== 'table'
                "
                    class="mt-4 w-full overflow-hidden rounded-[16px] border border-indigo-100 bg-gradient-to-br from-white via-indigo-50/30 to-violet-50/40 p-[18px] shadow-[0_5px_18px_rgba(79,70,229,0.04)]">

                    <div class="mb-4 flex items-center gap-2">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-blue-100 to-indigo-100 text-blue-600">
                            📊
                        </span>

                        <span class="text-[11px] font-bold uppercase tracking-[0.45px] text-indigo-700">
                            Visualization
                        </span>

                    </div>

                    <AnalyticsChart :result="result" />

                </div>

                <!-- Table -->

                <div v-if="
                    result.visualization?.type === 'table'
                "
                    class="mt-4 overflow-hidden rounded-[16px] border border-indigo-100 bg-white shadow-[0_5px_18px_rgba(79,70,229,0.04)]">

                    <div
                        class="flex items-center justify-between gap-[15px] border-b border-indigo-100 bg-gradient-to-r from-violet-50 via-white to-blue-50 px-[18px] py-4">

                        <div class="flex items-center gap-3">

                            <div
                                class="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-100 to-indigo-100 text-blue-600">

                                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                    stroke-width="2">

                                    <rect x="3" y="4" width="18" height="16" rx="2" />

                                    <path d="M3 10h18M9 4v16M15 4v16" />

                                </svg>

                            </div>

                            <div>

                                <h4 class="m-0 text-sm font-bold text-slate-900">
                                    Results
                                </h4>

                                <p class="mt-[3px] text-[11px] text-slate-400">
                                    Data returned from your query
                                </p>

                            </div>

                        </div>

                        <span
                            class="whitespace-nowrap rounded-full border border-violet-200 bg-gradient-to-r from-violet-50 to-indigo-50 px-[10px] py-[5px] text-[11px] font-bold text-violet-700">

                            {{
                                result.data?.row_count ??
                                result.data?.rows?.length ??
                                0
                            }}

                            rows

                        </span>

                    </div>

                    <div class="w-full overflow-x-auto">

                        <table class="min-w-[600px] w-full border-collapse">

                            <thead>

                                <tr>

                                    <th v-for="(column, columnIndex) in result.data?.columns || []" :key="column"
                                        class="whitespace-nowrap border-b border-indigo-100 px-4 py-[13px] text-left text-[11px] font-bold uppercase tracking-[0.35px]"
                                        :class="[
                                            columnIndex % 4 === 0
                                                ? 'bg-violet-50 text-violet-700'
                                                : '',
                                            columnIndex % 4 === 1
                                                ? 'bg-blue-50 text-blue-700'
                                                : '',
                                            columnIndex % 4 === 2
                                                ? 'bg-fuchsia-50 text-fuchsia-700'
                                                : '',
                                            columnIndex % 4 === 3
                                                ? 'bg-indigo-50 text-indigo-700'
                                                : '',
                                        ]">

                                        {{ column }}

                                    </th>

                                </tr>

                            </thead>

                            <tbody>

                                <tr v-for="(row, index) in result.data?.rows || []" :key="index"
                                    class="transition-colors duration-150 hover:bg-violet-50/50">

                                    <td v-for="(column, columnIndex) in result.data?.columns || []" :key="column"
                                        class="whitespace-nowrap border-b border-slate-100 px-4 py-[13px] text-left text-xs last:border-b-0"
                                        :class="columnIndex % 2 === 0
                                                ? 'text-slate-700'
                                                : 'text-indigo-700'
                                            ">

                                        {{ formatCell(row?.[column]) }}

                                    </td>

                                </tr>

                                <!-- FIXED: optional chaining syntax -->

                                <tr v-if="
                                    !result.data?.rows?.length
                                ">

                                    <td :colspan="result.data?.columns
                                            ?.length || 1
                                        " class="px-4 py-8 text-center text-xs text-slate-400">

                                        <div
                                            class="mx-auto mb-2 flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-400">
                                            ∅
                                        </div>

                                        No rows were returned.

                                    </td>

                                </tr>

                            </tbody>

                        </table>

                    </div>

                </div>

                <!-- Empty visualization fallback -->

                <div v-if="
                    !result.visualization &&
                    !result.data?.rows?.length &&
                    !result.insights?.insights?.length
                "
                    class="rounded-[16px] border border-violet-100 bg-gradient-to-br from-violet-50/50 via-white to-indigo-50/50 px-5 py-8 text-center">

                    <div
                        class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-violet-100 to-indigo-100 text-2xl text-violet-500">

                        ✦

                    </div>

                    <p class="mt-3 text-sm font-bold text-slate-700">

                        Analysis completed

                    </p>

                    <p class="mt-1 text-xs text-slate-400">

                        The analysis did not return
                        visualizable results.

                    </p>

                </div>

            </div>

        </div>

    </section>
</template>