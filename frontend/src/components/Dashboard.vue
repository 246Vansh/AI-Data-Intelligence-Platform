<script setup>
import { computed, ref, nextTick, watch } from "vue";

import DatasetOverview from "./DatasetOverview.vue";
import AnalyticsBuilder from "./AnalyticsBuilder.vue";
import DataPreview from "./DataPreview.vue";
import DatasetUpload from "./DatasetUpload.vue";
import DatasetMetadata from "./DatasetMetadata.vue";

import {
    useAnalysisContext,
    ANALYSIS_MODES,
    ANALYSIS_MODE_LABELS,
} from "../composables/useAnalysisContext";

// =========================================================
// PROPS
// =========================================================

const props = defineProps({
    incomingQuestion: {
        type: String,
        default: "",
    },
});

// =========================================================
// STATE
// =========================================================

const refreshKey = ref(0);
const selectedQuestion = ref("");
const question = ref("");
const activeSection = ref("overview");

const error = ref(null);
const result = ref(null);

// =========================================================
// DATASET STATE (central multi-dataset state)
// =========================================================
//
// `datasets` holds every dataset uploaded this session (each one
// keeps living in the backend registry by its own dataset_id, so
// switching back and forth never loses data).

const datasets = ref([]);

// =========================================================
// ANALYSIS CONTEXT (mode + selected dataset_ids)
// =========================================================
//
// `primaryDatasetId` is the dataset driving every dataset-dependent
// panel below (Overview, Preview, Schema, Ask Your Data execution) -
// in SINGLE mode it's the only selected dataset; in COMPARISON /
// CROSS_DATASET it's the anchor dataset until real multi-dataset
// execution exists (Step 2+).

const {
    mode: analysisMode,
    datasetIds: selectedDatasetIds,
    primaryDatasetId: selectedDatasetId,
    analysisContext,
    isSelected: isDatasetSelected,
    selectSingle: selectDatasetSingle,
    toggleDataset: toggleDatasetSelection,
    setMode: setAnalysisMode,
} = useAnalysisContext();

const analysisModeOptions = [
    { value: ANALYSIS_MODES.SINGLE, label: ANALYSIS_MODE_LABELS[ANALYSIS_MODES.SINGLE] },
    { value: ANALYSIS_MODES.COMPARISON, label: ANALYSIS_MODE_LABELS[ANALYSIS_MODES.COMPARISON] },
    { value: ANALYSIS_MODES.CROSS_DATASET, label: ANALYSIS_MODE_LABELS[ANALYSIS_MODES.CROSS_DATASET] },
];

const selectedDataset = computed(() =>
    datasets.value.find(
        (dataset) => dataset.dataset_id === selectedDatasetId.value,
    ) || null,
);

// Resolves the selected dataset_ids to their dataset entries through
// the existing dataset store - no separate/duplicated dataset list.
const selectedDatasetEntries = computed(() =>
    selectedDatasetIds.value
        .map((id) => datasets.value.find((dataset) => dataset.dataset_id === id))
        .filter(Boolean),
);

const selectedDatasetNames = computed(() =>
    selectedDatasetEntries.value.map((dataset) => dataset.filename),
);

const analysisModeLabel = computed(
    () => ANALYSIS_MODE_LABELS[analysisMode.value] || analysisMode.value,
);

// Drives the header status pill - kept in sync with the same
// selection state the sidebar's mode selector / status panel and
// the Ask Your Data banner already read from, instead of a static
// label that never reflected what's actually selected.
const headerStatusText = computed(() => {
    if (!selectedDatasetEntries.value.length) {
        return "No Dataset Loaded";
    }

    if (analysisMode.value === ANALYSIS_MODES.SINGLE) {
        return "Dataset Loaded";
    }

    return `${analysisModeLabel.value} · ${selectedDatasetEntries.value.length} Datasets`;
});

function formatNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : "—";
}

// =========================================================
// DATASET UPLOAD / SELECTION
// =========================================================

// Every dataset-dependent panel keys off `selectedDatasetId`
// (the primary/anchor dataset), so remounting/resetting only needs
// to react to that changing, regardless of which selection path
// (single click, checkbox toggle, mode switch) caused it.
watch(selectedDatasetId, (newId, oldId) => {
    if (newId === oldId) {
        return;
    }

    // Force every dataset-dependent panel to remount against the
    // newly selected dataset_id instead of reusing state (and any
    // still-in-flight requests) built for the previous one.
    refreshKey.value += 1;

    selectedQuestion.value = "";
    question.value = "";
    error.value = null;
    result.value = null;
});

function selectDataset(datasetId) {
    if (analysisMode.value === ANALYSIS_MODES.SINGLE) {
        selectDatasetSingle(datasetId);
    } else {
        toggleDatasetSelection(datasetId);
    }
}

function handleDatasetUploaded(uploadResponse) {
    const datasetId = uploadResponse?.dataset_id;

    if (!datasetId) {
        return;
    }

    const entry = {
        dataset_id: datasetId,
        filename: uploadResponse.filename || "Uploaded dataset",
        rows: uploadResponse.rows,
        columns: uploadResponse.columns,
    };

    const existingIndex = datasets.value.findIndex(
        (dataset) => dataset.dataset_id === datasetId,
    );

    if (existingIndex >= 0) {
        datasets.value.splice(existingIndex, 1, entry);
    } else {
        datasets.value.push(entry);
    }

    // A newly uploaded dataset always becomes active: in SINGLE mode
    // it replaces the current selection; in COMPARISON / CROSS_DATASET
    // it's added to the active set.
    selectDataset(datasetId);
}

function setActiveSection(section) {
    activeSection.value = section;
}


function handleQuestionSelected(newQuestion) {
    if (!newQuestion) {
        return;
    }

    selectedQuestion.value = newQuestion;
    question.value = newQuestion;

    error.value = null;
    result.value = null;

    nextTick(() => {
        const askDataSection =
            document.getElementById("ask-data");

        if (askDataSection) {
            askDataSection.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        }
    });
}


watch(
    () => props.incomingQuestion,
    (newQuestion) => {
        if (!newQuestion) {
            return;
        }

        handleQuestionSelected(newQuestion);
    },
    {
        immediate: true,
    },
);
</script>

<template>
    <div class="min-h-screen bg-[#f6f7fb] text-[#172033] selection:bg-violet-100 selection:text-violet-800">

        <!-- =====================================================
             SIDEBAR
        ====================================================== -->

        <aside class="fixed inset-y-0 left-0 z-40 hidden w-[230px] border-r border-slate-200/80 bg-white lg:block">

            <div class="flex h-full flex-col px-4 py-5">

                <!-- Brand -->

                <div class="mb-8 px-2">

                    <div class="flex items-center gap-3">

                        <div
                            class="relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-indigo-600 to-blue-600 text-lg font-bold text-white shadow-[0_8px_22px_rgba(99,102,241,0.25)]">

                            <span class="relative z-10">
                                ✦
                            </span>

                            <div class="absolute -right-2 -top-2 h-7 w-7 rounded-full bg-white/20 blur-sm">
                            </div>

                        </div>

                        <div class="min-w-0">

                            <p class="truncate text-[13px] font-bold tracking-[-0.2px] text-slate-900">
                                Data Intelligence
                            </p>

                            <p class="mt-0.5 text-[10px] font-medium text-slate-400">
                                AI Analytics Platform
                            </p>

                        </div>

                    </div>

                </div>

                <!-- Navigation Label -->

                <div class="mb-2 px-2 text-[9px] font-bold uppercase tracking-[0.7px] text-slate-400">
                    Workspace
                </div>

                <!-- Navigation -->

                <nav class="space-y-1">

                    <!-- Overview -->
                    <a href="#overview" @click="setActiveSection('overview')" :class="activeSection === 'overview'
                        ? 'bg-gradient-to-r from-violet-50 to-indigo-50 font-semibold text-violet-700'
                        : 'font-medium text-slate-500 hover:bg-violet-50 hover:text-violet-700'
                        "
                        class="group relative flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] transition-all duration-200">

                        <span :class="activeSection === 'overview'
                            ? 'bg-violet-100 text-violet-600'
                            : 'bg-slate-100 text-slate-500 group-hover:bg-violet-100 group-hover:text-violet-600'
                            " class="flex h-7 w-7 items-center justify-center rounded-lg text-sm transition">
                            ⌂
                        </span>

                        <span>
                            Overview
                        </span>

                        <span v-if="activeSection === 'overview'"
                            class="ml-auto h-1.5 w-1.5 rounded-full bg-violet-500"></span>

                    </a>

                    <!-- Data Preview -->
                    <a href="#data-preview" @click="setActiveSection('data-preview')" :class="activeSection === 'data-preview'
                        ? 'bg-gradient-to-r from-blue-50 to-indigo-50 font-semibold text-blue-700'
                        : 'font-medium text-slate-500 hover:bg-blue-50 hover:text-blue-700'
                        "
                        class="group relative flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] transition-all duration-200">

                        <span :class="activeSection === 'data-preview'
                            ? 'bg-blue-100 text-blue-600'
                            : 'bg-slate-100 text-slate-500 group-hover:bg-blue-100 group-hover:text-blue-600'
                            " class="flex h-7 w-7 items-center justify-center rounded-lg text-sm transition">
                            ▤
                        </span>

                        <span>
                            Data Preview
                        </span>

                        <span v-if="activeSection === 'data-preview'"
                            class="ml-auto h-1.5 w-1.5 rounded-full bg-blue-500"></span>

                    </a>


                    <!-- Dataset Schema -->
                    <a href="#dataset-schema" @click="setActiveSection('dataset-schema')" :class="activeSection === 'dataset-schema'
                        ? 'bg-gradient-to-r from-emerald-50 to-teal-50 font-semibold text-emerald-700'
                        : 'font-medium text-slate-500 hover:bg-emerald-50 hover:text-emerald-700'
                        "
                        class="group relative flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] transition-all duration-200">

                        <span :class="activeSection === 'dataset-schema'
                            ? 'bg-emerald-100 text-emerald-600'
                            : 'bg-slate-100 text-slate-500 group-hover:bg-emerald-100 group-hover:text-emerald-600'
                            " class="flex h-7 w-7 items-center justify-center rounded-lg text-sm transition">
                            ▱
                        </span>

                        <span>
                            Dataset Schema
                        </span>

                        <span v-if="activeSection === 'dataset-schema'"
                            class="ml-auto h-1.5 w-1.5 rounded-full bg-emerald-500"></span>

                    </a>

                    <!-- Ask Your Data -->
                    <a href="#ask-data" @click="setActiveSection('ask-data')" :class="activeSection === 'ask-data'
                        ? 'bg-gradient-to-r from-violet-50 to-indigo-50 font-semibold text-violet-700'
                        : 'font-medium text-slate-500 hover:bg-violet-50 hover:text-violet-700'
                        "
                        class="group relative flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] transition-all duration-200">

                        <span :class="activeSection === 'ask-data'
                            ? 'bg-violet-100 text-violet-600'
                            : 'bg-slate-100 text-slate-500 group-hover:bg-violet-100 group-hover:text-violet-600'
                            " class="flex h-7 w-7 items-center justify-center rounded-lg text-sm transition">
                            ✦
                        </span>

                        <span>
                            Ask Your Data
                        </span>

                        <span v-if="activeSection === 'ask-data'"
                            class="ml-auto h-1.5 w-1.5 rounded-full bg-violet-500"></span>

                    </a>


                    <!-- Insights -->
                    <a href="#insights" @click="setActiveSection('insights')" :class="activeSection === 'insights'
                        ? 'bg-gradient-to-r from-amber-50 to-orange-50 font-semibold text-amber-700'
                        : 'font-medium text-slate-500 hover:bg-amber-50 hover:text-amber-700'
                        "
                        class="group relative flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] transition-all duration-200">

                        <span :class="activeSection === 'insights'
                            ? 'bg-amber-100 text-amber-600'
                            : 'bg-slate-100 text-slate-500 group-hover:bg-amber-100 group-hover:text-amber-600'
                            " class="flex h-7 w-7 items-center justify-center rounded-lg text-sm transition">
                            ◈
                        </span>

                        <span>
                            Insights
                        </span>

                        <span v-if="activeSection === 'insights'"
                            class="ml-auto h-1.5 w-1.5 rounded-full bg-amber-500"></span>

                    </a>

                </nav>

                <!-- Divider -->

                <div class="my-6 border-t border-slate-100"></div>

                <!-- Datasets Label -->

                <div class="mb-2 px-2 text-[9px] font-bold uppercase tracking-[0.7px] text-slate-400">
                    Datasets
                </div>

                <!-- =================================================
                     ANALYSIS MODE SELECTOR
                ================================================== -->

                <div class="mb-3 grid grid-cols-3 gap-1 rounded-xl bg-slate-100 p-1">

                    <button v-for="modeOption in analysisModeOptions" :key="modeOption.value" type="button"
                        @click="setAnalysisMode(modeOption.value)" :title="modeOption.label"
                        :class="analysisMode === modeOption.value
                            ? 'bg-white text-violet-700 shadow-sm'
                            : 'text-slate-500 hover:text-violet-600'
                            "
                        class="truncate rounded-lg px-1.5 py-1.5 text-[9.5px] font-bold transition-all duration-200 cursor-pointer">
                        {{ modeOption.label }}
                    </button>

                </div>

                <!-- =================================================
                     DATASET LIST / SWITCHER
                ================================================== -->

                <div class="mb-4 space-y-1.5">

                    <p v-if="!datasets.length"
                        class="rounded-xl border border-dashed border-slate-200 px-3 py-3 text-[10px] leading-4 text-slate-400">
                        No datasets uploaded yet. Upload a CSV to get started.
                    </p>

                    <button v-for="dataset in datasets" :key="dataset.dataset_id" type="button"
                        @click="selectDataset(dataset.dataset_id)" :class="isDatasetSelected(dataset.dataset_id)
                            ? 'border-violet-200 bg-gradient-to-r from-violet-50 to-indigo-50 text-violet-700'
                            : 'border-slate-100 bg-white text-slate-500 hover:border-violet-200 hover:bg-violet-50 hover:text-violet-700'
                            "
                        class="group flex w-full items-center gap-2 rounded-xl border px-2.5 py-2 text-left transition-all duration-200">

                        <!-- Single mode: dot indicator (unchanged) -->
                        <span v-if="analysisMode === 'single'" :class="isDatasetSelected(dataset.dataset_id)
                            ? 'bg-violet-500'
                            : 'bg-slate-300'
                            " class="h-1.5 w-1.5 shrink-0 rounded-full"></span>

                        <!-- Comparison / cross-dataset mode: checkbox indicator -->
                        <span v-else :class="isDatasetSelected(dataset.dataset_id)
                            ? 'border-violet-500 bg-violet-500 text-white'
                            : 'border-slate-300 bg-white'
                            "
                            class="flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-all duration-200">
                            <svg v-if="isDatasetSelected(dataset.dataset_id)" class="h-2.5 w-2.5" viewBox="0 0 24 24"
                                fill="none" stroke="currentColor" stroke-width="3">
                                <path d="m5 12 4 4L19 6" stroke-linecap="round" stroke-linejoin="round" />
                            </svg>
                        </span>

                        <span class="min-w-0 flex-1">

                            <span class="block truncate text-[11px] font-semibold" :title="dataset.filename">
                                {{ dataset.filename }}
                            </span>

                            <span class="block text-[9px] text-slate-400">
                                {{ formatNumber(dataset.rows) }} rows · {{ formatNumber(dataset.columns) }} cols
                            </span>

                        </span>

                        <span v-if="analysisMode === 'single' && isDatasetSelected(dataset.dataset_id)"
                            class="shrink-0 text-[10px] font-bold text-violet-500">
                            ✓
                        </span>

                    </button>

                </div>

                <!-- Analysis Context Status -->

                <div v-if="selectedDatasetEntries.length"
                    class="rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50/80 to-teal-50/40 p-3.5">

                    <div class="flex items-center gap-2.5">

                        <div
                            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600">
                            {{ analysisMode === 'single' ? '✓' : '⇄' }}
                        </div>

                        <div class="min-w-0">

                            <p class="text-[9px] font-bold uppercase tracking-[0.5px] text-emerald-600">
                                Analysis Mode: {{ analysisModeLabel }}
                            </p>

                            <p class="mt-0.5 truncate text-[11px] font-bold text-emerald-800"
                                :title="selectedDatasetNames.join(', ')">
                                {{ selectedDatasetNames.join(', ') }}
                            </p>

                            <p class="mt-0.5 text-[9px] text-emerald-600">
                                {{ selectedDatasetEntries.length }}
                                dataset{{ selectedDatasetEntries.length === 1 ? '' : 's' }} selected
                            </p>

                        </div>

                    </div>

                </div>

            </div>

        </aside>

        <!-- =====================================================
             MAIN APPLICATION
        ====================================================== -->

        <div class="lg:pl-[210px]">

            <!-- =================================================
                 HEADER
            ================================================== -->

            <header class="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">

                <div class="flex min-h-[70px] items-center justify-between px-5 sm:px-8 lg:px-10">

                    <!-- Brand -->

                    <div class="flex items-center gap-3">

                        <div
                            class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 text-base font-bold text-white shadow-md lg:hidden">
                            ✦
                        </div>

                        <div>

                            <div class="flex items-center gap-2">

                                <h1 class="text-[14px] font-bold tracking-[-0.25px] text-slate-900 sm:text-[16px]">
                                    AI Data Intelligence Platform
                                </h1>

                                <span
                                    class="hidden rounded-full bg-violet-50 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.5px] text-violet-600 sm:inline-block">
                                    Beta
                                </span>

                            </div>

                            <p class="mt-0.5 text-[10px] text-slate-400 sm:text-xs">
                                Interactive data analytics workspace
                            </p>

                        </div>

                    </div>

                    <!-- Header Actions -->

                    <div class="flex items-center gap-2 sm:gap-3">

                        <div class="flex items-center gap-2 rounded-full border px-3 py-1.5 text-[10px] font-bold sm:px-3.5 sm:py-2 sm:text-xs"
                            :class="selectedDatasetEntries.length
                                ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
                                : 'border-slate-200 bg-slate-50 text-slate-500'
                                ">

                            <span class="relative flex h-2 w-2">

                                <span v-if="selectedDatasetEntries.length"
                                    class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50">
                                </span>

                                <span class="relative inline-flex h-2 w-2 rounded-full"
                                    :class="selectedDatasetEntries.length ? 'bg-emerald-500' : 'bg-slate-300'">
                                </span>

                            </span>

                            <span class="hidden sm:inline">
                                {{ headerStatusText }}
                            </span>

                            <span class="sm:hidden">
                                {{ selectedDatasetEntries.length ? 'Ready' : 'No Data' }}
                            </span>

                        </div>

                        <button type="button"
                            class="hidden h-9 w-9 place-items-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500 transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-600 sm:grid"
                            title="Theme">
                            ☾
                        </button>

                        <div
                            class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-800 to-slate-950 text-[10px] font-bold text-white shadow-sm">
                            AI
                        </div>

                    </div>

                </div>

            </header>

            <!-- =================================================
                 CONTENT
            ================================================== -->

            <main class="mx-auto max-w-[1500px] px-5 pb-20 pt-7 sm:px-8 lg:px-10">

                <!-- =================================================
                     HERO
                ================================================== -->

                <section class="group relative mb-8 overflow-hidden rounded-[28px] border border-violet-100 bg-white">

                    <div class="absolute inset-0 bg-gradient-to-br from-white via-violet-50/50 to-indigo-50/80">
                    </div>

                    <div
                        class="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-violet-300/20 blur-3xl">
                    </div>

                    <div
                        class="pointer-events-none absolute -bottom-32 right-1/3 h-64 w-64 rounded-full bg-blue-300/15 blur-3xl">
                    </div>

                    <div
                        class="pointer-events-none absolute left-1/3 top-0 h-40 w-40 rounded-full bg-fuchsia-200/10 blur-3xl">
                    </div>

                    <div class="relative z-10 flex min-h-[330px] items-center px-6 py-10 sm:px-8 lg:px-11 lg:py-12">

                        <div class="max-w-[720px]">

                            <div
                                class="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-100 bg-white/90 px-3 py-1.5 text-[10px] font-bold text-violet-700 shadow-sm">

                                <span
                                    class="flex h-5 w-5 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                                    ✦
                                </span>

                                AI-POWERED ANALYTICS

                            </div>

                            <h2
                                class="max-w-[760px] text-4xl font-extrabold leading-[1.02] tracking-[-2px] text-slate-950 sm:text-5xl lg:text-[58px]">

                                Turn your data into

                                <span
                                    class="bg-gradient-to-r from-violet-600 via-indigo-600 to-blue-600 bg-clip-text text-transparent">
                                    decisions.
                                </span>

                            </h2>

                            <p
                                class="mt-5 max-w-[650px] text-[13px] leading-6 text-slate-500 sm:text-[15px] lg:text-[16px]">

                                Explore your dataset, understand its structure,
                                discover patterns, and ask questions using
                                natural language.

                            </p>

                            <div class="mt-6 flex flex-wrap gap-2">

                                <span
                                    class="rounded-lg border border-violet-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-violet-700">
                                    Natural Language
                                </span>

                                <span
                                    class="rounded-lg border border-blue-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-blue-700">
                                    Smart Analytics
                                </span>

                                <span
                                    class="rounded-lg border border-emerald-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-emerald-700">
                                    Visual Insights
                                </span>

                            </div>

                        </div>

                        <!-- Hero Mini Analytics -->

                        <div
                            class="absolute right-8 top-1/2 hidden h-[205px] w-[300px] -translate-y-1/2 overflow-hidden rounded-[24px] border border-white/80 bg-white/80 p-5 shadow-[0_20px_50px_rgba(79,70,229,0.12)] backdrop-blur-md xl:block">

                            <div class="mb-4 flex items-center justify-between">

                                <div>

                                    <p class="text-[9px] font-bold uppercase tracking-[0.5px] text-slate-400">
                                        Performance
                                    </p>

                                    <p class="mt-1 text-sm font-bold text-slate-800">
                                        Dataset Overview
                                    </p>

                                </div>

                                <div class="rounded-lg bg-emerald-50 px-2 py-1 text-[9px] font-bold text-emerald-600">
                                    +18.4%
                                </div>

                            </div>

                            <div class="flex h-[105px] items-end gap-2">

                                <div class="h-[34%] flex-1 rounded-t-md bg-gradient-to-t from-violet-500 to-violet-300">
                                </div>

                                <div class="h-[52%] flex-1 rounded-t-md bg-gradient-to-t from-indigo-500 to-indigo-300">
                                </div>

                                <div class="h-[43%] flex-1 rounded-t-md bg-gradient-to-t from-blue-500 to-blue-300">
                                </div>

                                <div class="h-[69%] flex-1 rounded-t-md bg-gradient-to-t from-violet-600 to-violet-300">
                                </div>

                                <div class="h-[83%] flex-1 rounded-t-md bg-gradient-to-t from-indigo-600 to-indigo-300">
                                </div>

                                <div class="h-[100%] flex-1 rounded-t-md bg-gradient-to-t from-blue-600 to-blue-300">
                                </div>

                            </div>

                            <div class="mt-3 flex items-center justify-between border-t border-slate-100 pt-2">

                                <span class="text-[8px] text-slate-400">
                                    Data trend
                                </span>

                                <span class="flex items-center gap-1 text-[8px] font-semibold text-violet-600">

                                    <span class="h-1.5 w-1.5 rounded-full bg-violet-500">
                                    </span>

                                    AI analysis

                                </span>

                            </div>

                        </div>

                    </div>

                </section>

                <!-- =================================================
                     UPLOAD
                ================================================== -->

                <section id="upload" class="scroll-mt-24">

                    <DatasetUpload :active-dataset="selectedDataset" @dataset-uploaded="handleDatasetUploaded" />

                </section>

                <!-- =================================================
                     OVERVIEW
                ================================================== -->

                <section id="overview" class="scroll-mt-24 pt-8">

                    <DatasetOverview :key="`overview-${refreshKey}`" :dataset-id="selectedDatasetId" />

                </section>

                <!-- =================================================
                     DATA PREVIEW
                ================================================== -->

                <section id="data-preview" class="scroll-mt-24 pt-8">

                    <DataPreview :key="`preview-${refreshKey}`" :dataset-id="selectedDatasetId" />

                </section>

                <!-- =================================================
                     SCHEMA
                ================================================== -->

                <section id="dataset-schema" class="scroll-mt-24 pt-8">

                    <DatasetMetadata :key="`metadata-${refreshKey}`" :dataset-id="selectedDatasetId"
                        @question-selected="handleQuestionSelected" />

                </section>

                <!-- =================================================
                     INSIGHTS
                ================================================== -->

                <section id="insights" class="scroll-mt-24 pt-4">
                </section>

                <!-- =================================================
                     ASK YOUR DATA
                ================================================== -->

                <section id="ask-data" class="scroll-mt-24 pt-8">

                    <AnalyticsBuilder :key="`builder-${refreshKey}`" :incoming-question="selectedQuestion"
                        :dataset-id="selectedDatasetId" :analysis-mode="analysisMode"
                        :selected-dataset-ids="selectedDatasetIds" :selected-dataset-names="selectedDatasetNames" />

                </section>

            </main>

        </div>

    </div>
</template>