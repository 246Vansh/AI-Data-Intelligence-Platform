<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetPreview } from "../services/api";

const PREVIEW_ROW_LIMIT = 10;

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
});

const dataset = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);
const searchQuery = ref("");

async function loadPreview(options = {}) {
    const isRefresh = options.refresh === true;

    // Captured so a response that resolves after the user has
    // already switched datasets can be detected and ignored below.
    const requestedDatasetId = props.datasetId;

    // No dataset selected - see DatasetOverview.vue's loadProfile()
    // for why this must not fall back to the legacy no-id endpoint.
    if (!requestedDatasetId) {
        dataset.value = null;
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

        const response = await getDatasetPreview(requestedDatasetId);

        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        dataset.value = response;
    } catch (err) {
        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        console.error("Dataset preview error:", err);

        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load the dataset preview.";
    } finally {
        if (requestedDatasetId === props.datasetId) {
            loading.value = false;
            refreshing.value = false;
        }
    }
}

const sourceRows = computed(() =>
    Array.isArray(dataset.value?.rows)
        ? dataset.value.rows
        : [],
);

const filteredRows = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();

    if (!query) {
        return sourceRows.value.slice(0, PREVIEW_ROW_LIMIT);
    }

    return sourceRows.value
        .filter((row) =>
            Object.values(row || {}).some((value) =>
                String(value ?? "")
                    .toLowerCase()
                    .includes(query),
            ),
        )
        .slice(0, PREVIEW_ROW_LIMIT);
});

const totalRowCount = computed(() => sourceRows.value.length);

const visibleRowCount = computed(() => filteredRows.value.length);

const columnCount = computed(() =>
    Array.isArray(dataset.value?.columns)
        ? dataset.value.columns.length
        : 0,
);

const isSearchActive = computed(() =>
    Boolean(searchQuery.value.trim()),
);

function formatCell(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    if (typeof value === "number") {
        return new Intl.NumberFormat("en-US", {
            maximumFractionDigits: 2,
        }).format(value);
    }

    return String(value);
}

function clearSearch() {
    searchQuery.value = "";
}

function getColumnWidth(column) {
    const name = String(column || "").toLowerCase();

    /*
     * Wider fields
     */
    if (
        name.includes("description") ||
        name.includes("summary") ||
        name.includes("overview") ||
        name.includes("cast")
    ) {
        return "280px";
    }

    /*
     * Medium fields
     */
    if (
        name.includes("title") ||
        name.includes("director") ||
        name.includes("country") ||
        name.includes("listed")
    ) {
        return "170px";
    }

    /*
     * Smaller fields
     */
    if (
        name.includes("date") ||
        name.includes("year") ||
        name.includes("rating") ||
        name.includes("duration")
    ) {
        return "130px";
    }

    /*
     * Default column width
     *
     * 120px prevents the last column from being squeezed
     * into a partially visible state.
     */
    return "120px";
}

onMounted(() => {
    loadPreview();
});
</script>

<template>
    <section class="mt-5 w-full">

        <!-- =====================================================
             HEADER
        ====================================================== -->

        <div class="mb-4 flex items-center justify-between gap-3 max-[650px]:items-start">

            <div class="flex min-w-0 items-center gap-3">

                <!-- Header Icon -->
                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 via-violet-500 to-fuchsia-500 text-white shadow-md shadow-violet-200/60">

                    <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                        <rect x="3" y="3" width="18" height="18" rx="4" />
                        <path d="M3 9h18" />
                        <path d="M9 9v12" />
                        <path d="M13 13h4" />
                        <path d="M13 17h4" />
                    </svg>

                </div>

                <div class="min-w-0">

                    <div class="flex items-center gap-2">

                        <h2 class="text-lg font-bold tracking-tight text-slate-900">
                            Data Preview
                        </h2>

                        <span v-if="dataset"
                            class="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-gradient-to-r from-emerald-50 to-green-50 px-2 py-1 text-[9px] font-bold uppercase tracking-wide text-emerald-700">

                            <span
                                class="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.10)]"></span>

                            Live

                        </span>

                    </div>

                    <p class="mt-1 truncate text-[11px] text-slate-400">
                        Inspect records and fields before building your analysis.
                    </p>

                </div>

            </div>


            <!-- Refresh -->
            <button v-if="dataset" type="button" :disabled="refreshing"
                class="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg border border-violet-100 bg-gradient-to-r from-white to-violet-50/60 px-3 text-[10px] font-bold text-violet-600 shadow-sm transition duration-200 hover:border-violet-300 hover:from-violet-50 hover:to-indigo-50 hover:shadow-md disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                @click="loadPreview({ refresh: true })">

                <svg class="h-4 w-4" :class="{ 'animate-spin': refreshing }" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2">
                    <path d="M20 11a8.1 8.1 0 0 0-14.9-4" />
                    <path d="M4 4v5h5" />
                    <path d="M4 13a8.1 8.1 0 0 0 14.9 4" />
                    <path d="M20 20v-5h-5" />
                </svg>

                {{ refreshing ? "Refreshing" : "Refresh" }}

            </button>

        </div>


        <!-- =====================================================
             LOADING
        ====================================================== -->

        <div v-if="loading" class="overflow-hidden rounded-xl border border-violet-100 bg-white shadow-sm">

            <div
                class="flex items-center justify-between border-b border-violet-100 bg-gradient-to-r from-blue-50 via-violet-50 to-fuchsia-50 px-4 py-4">

                <div class="space-y-2">

                    <div class="h-3.5 w-32 animate-pulse rounded bg-violet-200"></div>

                    <div class="h-2.5 w-44 animate-pulse rounded bg-indigo-100"></div>

                </div>

                <div class="h-8 w-40 animate-pulse rounded-lg bg-white/80"></div>

            </div>

            <div>

                <div v-for="row in 7" :key="row" class="flex gap-3 border-b border-slate-100 px-4 py-4">

                    <div v-for="column in 7" :key="column"
                        class="h-3 flex-1 animate-pulse rounded bg-gradient-to-r from-slate-100 to-violet-100"></div>

                </div>

            </div>

        </div>


        <!-- =====================================================
             ERROR
        ====================================================== -->

        <div v-else-if="error"
            class="flex items-center gap-3 rounded-xl border border-red-200 bg-gradient-to-r from-red-50 via-orange-50 to-amber-50 px-5 py-4 shadow-sm">

            <div
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-red-100 to-orange-100 text-sm font-bold text-red-600">
                !
            </div>

            <div class="min-w-0 flex-1">

                <h3 class="text-xs font-bold text-slate-800">
                    Unable to load preview
                </h3>

                <p class="mt-1 truncate text-[10px] text-slate-500">
                    {{ error }}
                </p>

            </div>

            <button type="button"
                class="shrink-0 rounded-lg bg-gradient-to-r from-red-500 to-orange-500 px-3 py-2 text-[10px] font-bold text-white shadow-sm transition hover:from-red-600 hover:to-orange-600 hover:shadow-md"
                @click="loadPreview()">
                Retry
            </button>

        </div>


        <!-- =====================================================
             MAIN CARD
        ====================================================== -->

        <div v-else-if="dataset"
            class="overflow-hidden rounded-xl border border-violet-100 bg-white shadow-md shadow-violet-100/40">

            <!-- =================================================
                 TOOLBAR
            ================================================== -->

            <div
                class="border-b border-violet-100 bg-gradient-to-r from-blue-50/80 via-violet-50/70 to-fuchsia-50/60 px-4 py-4">

                <div class="flex items-center justify-between gap-4 max-[700px]:flex-col max-[700px]:items-stretch">

                    <!-- Dataset Info -->
                    <div class="flex min-w-0 items-center gap-3">

                        <div
                            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 via-violet-500 to-purple-600 text-white shadow-sm shadow-violet-200">

                            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="1.8">
                                <rect x="3" y="4" width="18" height="16" rx="3" />
                                <path d="M3 9h18" />
                                <path d="M8 9v11" />
                            </svg>

                        </div>

                        <div class="min-w-0">

                            <div class="flex items-center gap-2">

                                <h3 class="truncate text-sm font-bold text-slate-800">
                                    Dataset Records
                                </h3>

                                <span
                                    class="shrink-0 rounded-full border border-indigo-200 bg-gradient-to-r from-indigo-100 to-violet-100 px-2 py-1 text-[9px] font-bold text-indigo-700">
                                    {{ columnCount }} fields
                                </span>

                            </div>

                            <p class="mt-1 text-[10px] text-slate-400">

                                <strong class="text-blue-600">
                                    {{ visibleRowCount }}
                                </strong>

                                of

                                <strong class="text-violet-600">
                                    {{ totalRowCount }}
                                </strong>

                                records

                                <span v-if="isSearchActive" class="font-bold text-fuchsia-500">
                                    · filtered
                                </span>

                            </p>

                        </div>

                    </div>


                    <!-- SEARCH -->
                    <div class="relative w-full max-w-sm">

                        <svg class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-violet-400"
                            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">

                            <circle cx="11" cy="11" r="7" />
                            <path d="m20 20-4-4" />

                        </svg>


                        <!--
                            appearance-none + [&::-webkit-search-cancel-button]:hidden
                            removes the browser's native search X.
                        -->
                        <input v-model="searchQuery" type="search" placeholder="Search records..."
                            aria-label="Search dataset records"
                            class="h-9 w-full appearance-none rounded-lg border border-violet-200 bg-white/95 pl-9 pr-9 text-[10px] text-slate-700 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-violet-400 focus:ring-2 focus:ring-violet-100 [&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden [&::-ms-clear]:hidden" />


                        <!-- Only ONE custom clear button -->
                        <button v-if="searchQuery" type="button" aria-label="Clear search"
                            class="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-base leading-none text-slate-400 transition hover:bg-violet-100 hover:text-violet-600"
                            @click="clearSearch">
                            ×
                        </button>

                    </div>

                </div>

            </div>


            <!-- =================================================
                 EMPTY DATASET
            ================================================== -->

            <div v-if="!sourceRows.length"
                class="flex min-h-[280px] flex-col items-center justify-center bg-gradient-to-b from-white to-indigo-50/30 px-5 text-center">

                <div
                    class="flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-blue-100 via-violet-100 to-fuchsia-100 text-violet-500 shadow-sm">

                    <svg class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                        <rect x="3" y="4" width="18" height="16" rx="3" />
                        <path d="M3 9h18" />
                    </svg>

                </div>

                <h3 class="mt-4 text-sm font-bold text-slate-800">
                    No records available
                </h3>

                <p class="mt-1.5 max-w-xs text-[10px] leading-5 text-slate-400">
                    The uploaded dataset does not contain preview records.
                </p>

            </div>


            <!-- =================================================
                 NO RESULTS
            ================================================== -->

            <div v-else-if="!filteredRows.length"
                class="flex min-h-[280px] flex-col items-center justify-center bg-gradient-to-b from-white to-violet-50/30 px-5 text-center">

                <div
                    class="flex h-14 w-14 items-center justify-center rounded-xl bg-gradient-to-br from-slate-100 to-violet-100 text-violet-400 shadow-sm">

                    <svg class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                        <circle cx="11" cy="11" r="7" />
                        <path d="m20 20-4-4" />
                    </svg>

                </div>

                <h3 class="mt-4 text-sm font-bold text-slate-800">
                    No matching records
                </h3>

                <p class="mt-1.5 text-[10px] text-slate-400">

                    Nothing matches

                    <strong class="text-violet-500">
                        "{{ searchQuery }}"
                    </strong>

                </p>

                <button type="button"
                    class="mt-4 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2 text-[10px] font-bold text-white shadow-sm transition hover:from-violet-700 hover:to-indigo-700 hover:shadow-md"
                    @click="clearSearch">
                    Clear Search
                </button>

            </div>


            <!-- =================================================
                 TABLE
            ================================================== -->

            <div v-else>

                <!--
                    IMPORTANT:

                    1. Horizontal scrolling remains enabled.
                    2. Vertical scrolling remains enabled.
                    3. Scrollbars are visually hidden.
                    4. The table has a real minimum width.
                    5. Columns cannot be squeezed into half-visible
                       widths.
                -->

                <div
                    class="max-h-[560px] w-full overflow-auto overscroll-contain [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">

                    <table class="w-max min-w-full border-separate border-spacing-0 text-left"
                        style="table-layout: fixed">

                        <!-- =================================================
                             COLUMN WIDTHS
                        ================================================== -->

                        <colgroup>

                            <!-- Row number -->
                            <col style="width: 52px; min-width: 52px" />

                            <!-- Dataset columns -->
                            <col v-for="column in dataset.columns" :key="`width-${column}`" :style="{
                                width: getColumnWidth(column),
                                minWidth: getColumnWidth(column),
                            }" />

                        </colgroup>


                        <!-- =================================================
                             HEADER
                        ================================================== -->

                        <thead class="sticky top-0 z-10">

                            <tr>

                                <!-- Row number header -->
                                <th
                                    class="sticky left-0 z-20 h-12 w-[52px] min-w-[52px] border-b border-r border-indigo-200 bg-gradient-to-br from-blue-100 via-indigo-100 to-violet-100 px-3 text-center text-[9px] font-bold uppercase tracking-wide text-indigo-500">
                                    #
                                </th>


                                <!-- Dataset columns -->
                                <th v-for="(column, index) in dataset.columns" :key="column"
                                    class="h-12 border-b border-r border-violet-100 bg-gradient-to-b from-violet-50 via-white to-indigo-50/40 px-3.5">

                                    <div class="flex min-w-0 items-center gap-2">

                                        <span
                                            class="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-md bg-gradient-to-br from-violet-100 to-indigo-100 px-1.5 text-[8px] font-bold text-violet-600">
                                            {{ index + 1 }}
                                        </span>

                                        <span
                                            class="min-w-0 truncate text-[9px] font-bold uppercase tracking-wide text-slate-600"
                                            :title="column">
                                            {{ column }}
                                        </span>

                                    </div>

                                </th>

                            </tr>

                        </thead>


                        <!-- =================================================
                             BODY
                        ================================================== -->

                        <tbody>

                            <tr v-for="(row, rowIndex) in filteredRows" :key="rowIndex" class="group">

                                <!-- Row Number -->
                                <td
                                    class="sticky left-0 z-[5] h-[72px] w-[52px] min-w-[52px] border-b border-r border-indigo-100 bg-gradient-to-br from-blue-50 to-violet-50 px-3 text-center align-middle transition group-hover:from-violet-100 group-hover:to-fuchsia-100">

                                    <span
                                        class="inline-flex min-w-6 items-center justify-center rounded-md bg-white/90 px-1.5 py-1 text-[9px] font-bold text-violet-600 shadow-sm">
                                        {{ rowIndex + 1 }}
                                    </span>

                                </td>


                                <!-- Cells -->
                                <td v-for="(column, columnIndex) in dataset.columns" :key="column"
                                    class="h-[72px] border-b border-r border-slate-100 px-3.5 align-middle transition"
                                    :class="[
                                        columnIndex % 4 === 0
                                            ? 'bg-blue-50/25 group-hover:bg-blue-50/70'
                                            : columnIndex % 4 === 1
                                                ? 'bg-violet-50/20 group-hover:bg-violet-50/70'
                                                : columnIndex % 4 === 2
                                                    ? 'bg-fuchsia-50/15 group-hover:bg-fuchsia-50/60'
                                                    : 'bg-white group-hover:bg-indigo-50/60'
                                    ]">

                                    <div class="line-clamp-3 max-w-full overflow-hidden text-ellipsis text-[10px] leading-5 text-slate-600"
                                        :class="{
                                            'italic text-slate-300':
                                                row[column] === null ||
                                                row[column] === undefined ||
                                                row[column] === '',
                                        }" :title="String(row[column] ?? '')">
                                        {{ formatCell(row[column]) }}
                                    </div>

                                </td>

                            </tr>

                        </tbody>

                    </table>

                </div>


                <!-- =================================================
                     SCROLL HINT
                ================================================== -->

                <div
                    class="flex h-9 items-center justify-center gap-2 border-t border-violet-100 bg-gradient-to-r from-blue-50 via-violet-50 to-fuchsia-50 text-[9px] font-medium text-slate-500">

                    <span
                        class="flex h-4 w-4 items-center justify-center rounded-full bg-violet-100 font-bold text-violet-500">
                        ↔
                    </span>

                    <span>
                        Scroll horizontally to explore all fields
                    </span>

                    <span class="font-bold text-violet-500">
                        →
                    </span>

                </div>

            </div>


            <!-- =================================================
                 FOOTER
            ================================================== -->

            <div
                class="flex items-center justify-between gap-3 border-t border-violet-100 bg-gradient-to-r from-slate-50 via-violet-50/40 to-indigo-50/50 px-4 py-3 max-[520px]:items-start max-[520px]:flex-col">

                <div class="flex items-center gap-2 text-[9px] text-slate-400">

                    <span
                        class="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-[0_0_0_3px_rgba(16,185,129,0.08)]"></span>

                    <span>

                        Preview limited to first

                        <strong class="font-bold text-violet-600">
                            {{ PREVIEW_ROW_LIMIT }}
                        </strong>

                        records

                    </span>

                </div>


                <div class="flex items-center gap-3 text-[9px] text-slate-400">

                    <span>

                        <strong class="font-bold text-blue-600">
                            {{ visibleRowCount }}
                        </strong>

                        visible

                    </span>

                    <span class="h-4 w-px bg-violet-200"></span>

                    <span>

                        <strong class="font-bold text-violet-600">
                            {{ columnCount }}
                        </strong>

                        fields

                    </span>

                </div>

            </div>

        </div>

        <!-- =====================================================
             NO DATASET SELECTED
        ====================================================== -->

        <div v-else
            class="flex min-h-[220px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-5 text-center">
            <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
                <svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                    <rect x="3" y="3" width="18" height="18" rx="4" />
                    <path d="M3 9h18" />
                    <path d="M9 9v12" />
                </svg>
            </div>

            <h3 class="mt-3 text-sm font-bold text-slate-700">
                No dataset selected
            </h3>

            <p class="mt-1.5 max-w-xs text-[10px] leading-5 text-slate-400">
                Upload or select a dataset to preview its records.
            </p>
        </div>

    </section>
</template>