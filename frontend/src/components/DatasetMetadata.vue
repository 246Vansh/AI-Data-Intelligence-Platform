<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetMetadata } from "../services/api";

const emit = defineEmits(["question-selected"]);

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
});

const metadata = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);
const searchQuery = ref("");
const copiedQuestion = ref(null);

async function loadMetadata(options = {}) {
    const isRefresh = options.refresh === true;

    // Captured so a response that resolves after the user has
    // already switched datasets can be detected and ignored below.
    const requestedDatasetId = props.datasetId;

    // No dataset selected - see DatasetOverview.vue's loadProfile()
    // for why this must not fall back to the legacy no-id endpoint.
    if (!requestedDatasetId) {
        metadata.value = null;
        error.value = null;
        loading.value = false;
        refreshing.value = false;
        return;
    }

    try {
        if (isRefresh) {
            refreshing.value = true;
        } else {
            loading.value = true;
        }

        error.value = null;

        const response = await getDatasetMetadata(requestedDatasetId);

        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        metadata.value = response;
    } catch (err) {
        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        console.error("Dataset metadata error:", err);

        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load dataset metadata.";
    } finally {
        if (requestedDatasetId === props.datasetId) {
            loading.value = false;
            refreshing.value = false;
        }
    }
}

const columns = computed(() => {
    if (!metadata.value?.columns) {
        return [];
    }

    return Object.entries(metadata.value.columns).map(
        ([name, column]) => ({
            name,
            ...column,
        }),
    );
});

const filteredColumns = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();

    if (!query) {
        return columns.value;
    }

    return columns.value.filter((column) =>
        [column.name, column.role, column.data_type].some((value) =>
            String(value ?? "")
                .toLowerCase()
                .includes(query),
        ),
    );
});

const columnCount = computed(() => columns.value.length);
const visibleColumnCount = computed(() => filteredColumns.value.length);

const roleSummary = computed(() => {
    const summary = {};

    columns.value.forEach((column) => {
        const role = column.role || "unknown";
        summary[role] = (summary[role] || 0) + 1;
    });

    return summary;
});

const numericColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();
        const type = String(column.data_type || "").toLowerCase();

        return (
            role.includes("metric") ||
            role.includes("numeric") ||
            type.includes("int") ||
            type.includes("float") ||
            type.includes("double") ||
            type.includes("decimal") ||
            type.includes("number")
        );
    }),
);

const dimensionColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();

        return (
            role.includes("dimension") ||
            role.includes("categor")
        );
    }),
);

const dateColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();
        const type = String(column.data_type || "").toLowerCase();

        return (
            role.includes("date") ||
            role.includes("time") ||
            type.includes("date") ||
            type.includes("time")
        );
    }),
);

const totalMissingValues = computed(() =>
    columns.value.reduce((total, column) => {
        const value = Number(column.missing_count);
        return total + (Number.isFinite(value) ? value : 0);
    }, 0),
);

const totalUniqueValues = computed(() =>
    columns.value.reduce((total, column) => {
        const value = Number(column.unique_values);
        return total + (Number.isFinite(value) ? value : 0);
    }, 0),
);

const backendQuestions = computed(() => {
    const candidates = [
        metadata.value?.example_questions,
        metadata.value?.suggested_questions,
        metadata.value?.sample_questions,
    ];

    for (const candidate of candidates) {
        if (!Array.isArray(candidate)) {
            continue;
        }

        const questions = candidate
            .map((item) => {
                if (typeof item === "string") {
                    return item;
                }

                if (typeof item?.question === "string") {
                    return item.question;
                }

                if (typeof item?.text === "string") {
                    return item.text;
                }

                return null;
            })
            .filter(Boolean)
            .map((question) => question.trim())
            .filter(Boolean);

        if (questions.length) {
            return questions;
        }
    }

    return [];
});

function prettyColumnName(name) {
    if (!name) {
        return "this field";
    }

    return String(name)
        .replace(/_/g, " ")
        .replace(/-/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

const generatedQuestions = computed(() => {
    const questions = [];
    const metric = numericColumns.value[0]?.name || null;
    const secondMetric = numericColumns.value[1]?.name || null;
    const dimension = dimensionColumns.value[0]?.name || null;
    const secondDimension = dimensionColumns.value[1]?.name || null;
    const date = dateColumns.value[0]?.name || null;

    if (metric) {
        questions.push(
            `What is the total ${prettyColumnName(metric)}?`,
            `What is the average ${prettyColumnName(metric)}?`,
            `What are the highest and lowest ${prettyColumnName(metric)} values?`,
        );
    }

    if (dimension && metric) {
        questions.push(
            `What are the top categories by ${prettyColumnName(metric)}?`,
            `Which ${prettyColumnName(dimension)} has the highest ${prettyColumnName(metric)}?`,
            `How does ${prettyColumnName(metric)} vary across ${prettyColumnName(dimension)}?`,
        );
    }

    if (date && metric) {
        questions.push(
            `How does ${prettyColumnName(metric)} change over time?`,
            `What is the trend of ${prettyColumnName(metric)} by ${prettyColumnName(date)}?`,
        );
    }

    if (
        secondDimension &&
        metric &&
        secondDimension !== dimension
    ) {
        questions.push(
            `Compare ${prettyColumnName(metric)} across ${prettyColumnName(dimension)} and ${prettyColumnName(secondDimension)}.`,
        );
    }

    if (
        metric &&
        secondMetric &&
        metric !== secondMetric
    ) {
        questions.push(
            `How are ${prettyColumnName(metric)} and ${prettyColumnName(secondMetric)} related?`,
        );
    }

    if (dimension && !metric) {
        questions.push(
            `What are the most common ${prettyColumnName(dimension)} values?`,
            `How many unique ${prettyColumnName(dimension)} values are there?`,
        );
    }

    if (date && !metric) {
        questions.push(
            "What time period does the dataset cover?",
            `How many records are available for each ${prettyColumnName(date)} period?`,
        );
    }

    if (!questions.length) {
        questions.push(
            "What are the main patterns in this dataset?",
            "What are the most important insights from this data?",
            "Are there any unusual or unexpected values?",
            "Can you summarize this dataset?",
        );
    }

    return [...new Set(questions)].slice(0, 8);
});

const exampleQuestions = computed(() =>
    backendQuestions.value.length
        ? backendQuestions.value.slice(0, 8)
        : generatedQuestions.value,
);

async function selectQuestion(question) {
    emit("question-selected", question);

    try {
        if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(question);

            copiedQuestion.value = question;

            window.setTimeout(() => {
                if (copiedQuestion.value === question) {
                    copiedQuestion.value = null;
                }
            }, 1500);
        }
    } catch (err) {
        console.warn(
            "Unable to copy example question:",
            err,
        );
    }
}

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return value ?? "—";
    }

    return new Intl.NumberFormat("en-US").format(number);
}

function normalizeRole(role) {
    if (!role) {
        return "Unknown";
    }

    return String(role)
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeType(type) {
    if (!type) {
        return "Unknown";
    }

    return String(type)
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function roleClass(role) {
    const normalized = String(role || "").toLowerCase();

    if (
        normalized.includes("metric") ||
        normalized.includes("numeric")
    ) {
        return "border-blue-200 bg-gradient-to-r from-blue-50 to-cyan-50 text-blue-700";
    }

    if (
        normalized.includes("dimension") ||
        normalized.includes("categor")
    ) {
        return "border-violet-200 bg-gradient-to-r from-violet-50 to-fuchsia-50 text-violet-700";
    }

    if (
        normalized.includes("date") ||
        normalized.includes("time")
    ) {
        return "border-amber-200 bg-gradient-to-r from-amber-50 to-orange-50 text-amber-700";
    }

    if (
        normalized.includes("identifier") ||
        normalized.includes("id")
    ) {
        return "border-slate-200 bg-gradient-to-r from-slate-50 to-gray-50 text-slate-700";
    }

    return "border-emerald-200 bg-gradient-to-r from-emerald-50 to-teal-50 text-emerald-700";
}

function clearSearch() {
    searchQuery.value = "";
}

onMounted(() => {
    loadMetadata();
});
</script>

<template>
    <section class="mt-10 w-full">

        <!-- =====================================================
             HEADER
        ====================================================== -->

        <div class="mb-5 flex items-end justify-between gap-6 max-[760px]:flex-col max-[760px]:items-start">

            <div class="flex items-start gap-3">

                <!-- Colorful Header Icon -->
                <div
                    class="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500 via-violet-500 to-fuchsia-500 text-white shadow-lg shadow-violet-200/60">

                    <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">

                        <path d="M4 5h16" />
                        <path d="M4 12h16" />
                        <path d="M4 19h16" />
                        <circle cx="8" cy="5" r="1.5" />
                        <circle cx="16" cy="12" r="1.5" />
                        <circle cx="10" cy="19" r="1.5" />

                    </svg>

                </div>

                <div>

                    <div class="flex flex-wrap items-center gap-2">

                        <h2 class="m-0 text-xl font-bold tracking-[-0.35px] text-slate-900">
                            Dataset Schema
                        </h2>

                        <span v-if="metadata"
                            class="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-gradient-to-r from-emerald-50 to-teal-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.3px] text-emerald-700 shadow-sm">

                            <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>

                            Ready

                        </span>

                    </div>

                    <p class="mt-1 max-w-[620px] text-[13px] leading-5 text-slate-500">
                        Understand the columns, data types, analytical roles,
                        and quality characteristics available to the data
                        engine.
                    </p>

                </div>

            </div>


            <!-- Refresh -->
            <button v-if="metadata" type="button" :disabled="refreshing"
                class="inline-flex items-center gap-2 rounded-xl border border-violet-200 bg-gradient-to-r from-white via-violet-50 to-indigo-50 px-4 py-2.5 text-xs font-bold text-violet-700 shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-300 hover:from-violet-50 hover:to-fuchsia-50 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer"
                @click="loadMetadata({ refresh: true })">

                <svg class="h-3.5 w-3.5" :class="{ 'animate-spin': refreshing }" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2">

                    <path d="M20 11a8.1 8.1 0 0 0-14.9-4" />
                    <path d="M4 4v5h5" />
                    <path d="M4 13a8.1 8.1 0 0 0 14.9 4" />
                    <path d="M20 20v-5h-5" />

                </svg>

                {{ refreshing ? "Refreshing..." : "Refresh" }}

            </button>

        </div>


        <!-- =====================================================
             LOADING
        ====================================================== -->

        <div v-if="loading"
            class="overflow-hidden rounded-[20px] border border-violet-100 bg-white shadow-lg shadow-violet-100/40">

            <div class="border-b border-violet-100 bg-gradient-to-r from-blue-50 via-violet-50 to-fuchsia-50 p-5">

                <div class="mb-5 flex items-center justify-between gap-4">

                    <div class="space-y-2">

                        <div class="h-4 w-36 animate-pulse rounded bg-violet-200"></div>

                        <div class="h-3 w-56 animate-pulse rounded bg-indigo-100"></div>

                    </div>

                    <div class="h-9 w-56 animate-pulse rounded-lg bg-white/80"></div>

                </div>

            </div>

            <div class="grid grid-cols-1 gap-4 bg-slate-50/60 p-5 sm:grid-cols-2 lg:grid-cols-3">

                <div v-for="card in 6" :key="card" class="rounded-2xl border border-violet-100 bg-white p-5 shadow-sm">

                    <div class="flex items-center justify-between">

                        <div class="h-4 w-28 animate-pulse rounded bg-violet-100"></div>

                        <div class="h-6 w-16 animate-pulse rounded-full bg-fuchsia-100"></div>

                    </div>

                    <div class="mt-5 space-y-3">

                        <div class="h-3 w-24 animate-pulse rounded bg-slate-100"></div>

                        <div class="h-3 w-32 animate-pulse rounded bg-indigo-100"></div>

                        <div class="h-3 w-28 animate-pulse rounded bg-violet-100"></div>

                    </div>

                </div>

            </div>

        </div>


        <!-- =====================================================
             ERROR
        ====================================================== -->

        <div v-else-if="error"
            class="rounded-[20px] border border-red-200 bg-gradient-to-br from-red-50 via-white to-orange-50 p-6 shadow-lg shadow-red-100/40">

            <div class="flex items-start gap-4">

                <div
                    class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-red-100 to-orange-100 text-sm font-bold text-red-600 shadow-sm">
                    !
                </div>

                <div>

                    <h3 class="m-0 text-sm font-bold text-slate-900">
                        Unable to load dataset schema
                    </h3>

                    <p class="mt-1 text-[13px] leading-5 text-slate-500">
                        {{ error }}
                    </p>

                    <button type="button"
                        class="mt-4 rounded-xl bg-gradient-to-r from-red-500 to-orange-500 px-4 py-2.5 text-xs font-bold text-white shadow-md transition-all hover:-translate-y-0.5 hover:from-red-600 hover:to-orange-600 hover:shadow-lg"
                        @click="loadMetadata()">
                        Try Again
                    </button>

                </div>

            </div>

        </div>


        <!-- =====================================================
             METADATA
        ====================================================== -->

        <div v-else-if="metadata"
            class="overflow-hidden rounded-[20px] border border-violet-100 bg-white shadow-lg shadow-violet-100/40">


            <!-- =================================================
                 SUMMARY
            ================================================== -->

            <div class="grid grid-cols-1 border-b border-violet-100 sm:grid-cols-3">

                <!-- Columns -->
                <div
                    class="border-b border-violet-100 bg-gradient-to-br from-blue-50 to-cyan-50 px-5 py-5 sm:border-b-0 sm:border-r">

                    <div class="flex items-center justify-between">

                        <p class="m-0 text-[10px] font-bold uppercase tracking-[0.5px] text-blue-500">
                            Columns
                        </p>

                        <span
                            class="flex h-8 w-8 items-center justify-center rounded-lg bg-white/80 text-blue-500 shadow-sm">
                            #
                        </span>

                    </div>

                    <p class="mt-2 text-2xl font-extrabold text-blue-700">
                        {{ formatNumber(columnCount) }}
                    </p>

                    <p class="mt-1 text-[10px] font-medium text-blue-500">
                        Available fields
                    </p>

                </div>


                <!-- Unique -->
                <div
                    class="border-b border-violet-100 bg-gradient-to-br from-violet-50 to-fuchsia-50 px-5 py-5 sm:border-b-0 sm:border-r">

                    <div class="flex items-center justify-between">

                        <p class="m-0 text-[10px] font-bold uppercase tracking-[0.5px] text-violet-500">
                            Unique Values
                        </p>

                        <span
                            class="flex h-8 w-8 items-center justify-center rounded-lg bg-white/80 text-violet-500 shadow-sm">
                            ◈
                        </span>

                    </div>

                    <p class="mt-2 text-2xl font-extrabold text-violet-700">
                        {{ formatNumber(totalUniqueValues) }}
                    </p>

                    <p class="mt-1 text-[10px] font-medium text-violet-500">
                        Distinct values
                    </p>

                </div>


                <!-- Missing -->
                <div class="px-5 py-5 transition-colors duration-200" :class="totalMissingValues > 0
                        ? 'bg-amber-50'
                        : 'bg-emerald-50'
                    ">
                    <div class="flex items-center justify-between">

                        <p class="m-0 text-[10px] font-bold uppercase tracking-[0.5px]" :class="totalMissingValues > 0
                                ? 'text-amber-600'
                                : 'text-emerald-600'
                            ">
                            Missing Values
                        </p>

                        <span class="flex h-8 w-8 items-center justify-center rounded-lg bg-white/80 shadow-sm" :class="totalMissingValues > 0
                                ? 'text-amber-500'
                                : 'text-emerald-500'
                            ">
                            <svg v-if="totalMissingValues > 0" class="h-4 w-4" viewBox="0 0 24 24" fill="none"
                                stroke="currentColor" stroke-width="2">
                                <path d="M12 9v4" />
                                <path d="M12 17h.01" />
                                <path
                                    d="M10.3 3.8 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.8a2 2 0 0 0-3.4 0Z" />
                            </svg>

                            <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="2">
                                <path d="m5 12 4 4L19 6" />
                            </svg>
                        </span>

                    </div>

                    <p class="mt-2 text-2xl font-extrabold" :class="totalMissingValues > 0
                            ? 'text-amber-700'
                            : 'text-emerald-700'
                        ">
                        {{ formatNumber(totalMissingValues) }}
                    </p>

                    <p class="mt-1 text-[10px] font-medium" :class="totalMissingValues > 0
                            ? 'text-amber-500'
                            : 'text-emerald-500'
                        ">
                        {{
                            totalMissingValues > 0
                                ? "Needs attention"
                                : "No missing values"
                        }}
                    </p>

                </div>
            </div>


            <!-- =================================================
                 EXAMPLE QUESTIONS
            ================================================== -->

            <div v-if="exampleQuestions.length"
                class="border-b border-violet-100 bg-gradient-to-br from-violet-50/70 via-white to-blue-50/60 px-5 py-5">

                <div class="flex items-start justify-between gap-4 max-[650px]:flex-col">

                    <div class="flex items-start gap-3">

                        <div
                            class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-md shadow-violet-200">

                            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="1.8">

                                <path d="M12 3 14.5 9.5 21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"
                                    stroke-linejoin="round" />

                            </svg>

                        </div>

                        <div>

                            <h3 class="m-0 text-sm font-bold text-slate-900">
                                Example Questions
                            </h3>

                            <p class="mt-1 max-w-[620px] text-[11px] leading-5 text-slate-500">
                                Try these questions to explore your uploaded
                                dataset with the analytics engine.
                            </p>

                        </div>

                    </div>

                    <span
                        class="shrink-0 rounded-full border border-violet-200 bg-gradient-to-r from-violet-100 to-fuchsia-100 px-3 py-1.5 text-[9px] font-bold uppercase tracking-[0.4px] text-violet-700">
                        Dataset-aware
                    </span>

                </div>


                <div class="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">

                    <button v-for="(question, index) in exampleQuestions" :key="`${question}-${index}`" type="button"
                        class="group flex min-h-[62px] items-center justify-between gap-3 rounded-xl border border-violet-100 bg-white px-4 py-3 text-left shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:border-violet-300 hover:bg-gradient-to-r hover:from-violet-50 hover:to-fuchsia-50 hover:shadow-md cursor-pointer"
                        @click="selectQuestion(question)">

                        <span class="text-[11px] font-medium leading-5 text-slate-600 group-hover:text-violet-700">
                            {{ question }}
                        </span>

                        <span
                            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-violet-50 to-indigo-50 text-violet-500 transition-all group-hover:from-violet-500 group-hover:to-fuchsia-500 group-hover:text-white">

                            <svg v-if="copiedQuestion !== question" class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none"
                                stroke="currentColor" stroke-width="2">

                                <path d="M5 12h13" stroke-linecap="round" />
                                <path d="m13 6 6 6-6 6" stroke-linecap="round" stroke-linejoin="round" />

                            </svg>

                            <svg v-else class="h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none"
                                stroke="currentColor" stroke-width="2">

                                <path d="m5 12 4 4L19 6" stroke-linecap="round" stroke-linejoin="round" />

                            </svg>

                        </span>

                    </button>

                </div>

                <p class="mt-3 text-[9px] text-slate-400">
                    Click a question to use it in the analytics query.
                </p>

            </div>


            <!-- =================================================
                 FOOTER
            ================================================== -->

            <div
                class="flex items-center justify-between gap-4 border-t border-violet-100 bg-gradient-to-r from-slate-50 via-violet-50/50 to-indigo-50/50 px-[18px] py-3 text-[11px] text-slate-400 max-[600px]:flex-col max-[600px]:items-start">

                <div class="flex items-center gap-2">

                    <span class="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.10)]">
                    </span>

                    <span class="font-medium">
                        Schema loaded successfully
                    </span>

                </div>

                <span class="rounded-full bg-white px-3 py-1 font-bold text-violet-600 shadow-sm">

                    {{ visibleColumnCount }} visible columns

                </span>

            </div>

        </div>

        <!-- =====================================================
             NO DATASET SELECTED
        ====================================================== -->

        <div v-else
            class="flex min-h-[200px] flex-col items-center justify-center rounded-[20px] border border-dashed border-violet-100 bg-white px-5 text-center">
            <div
                class="flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-50 text-violet-400">
                <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M4 5h16" />
                    <path d="M4 12h16" />
                    <path d="M4 19h16" />
                    <circle cx="8" cy="5" r="1.5" />
                    <circle cx="16" cy="12" r="1.5" />
                    <circle cx="10" cy="19" r="1.5" />
                </svg>
            </div>

            <h3 class="mt-3 text-sm font-bold text-slate-700">
                No dataset selected
            </h3>

            <p class="mt-1.5 max-w-xs text-[11px] leading-5 text-slate-400">
                Upload or select a dataset to view its schema.
            </p>
        </div>

    </section>
</template>