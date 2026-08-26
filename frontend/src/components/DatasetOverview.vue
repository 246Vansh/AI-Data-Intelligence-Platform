<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetProfile } from "../services/api";

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
});

const profile = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);

async function loadProfile(options = {}) {
    const isRefresh = options.refresh === true;

    // Captured so a response that resolves after the user has
    // already switched datasets can be detected and ignored below.
    const requestedDatasetId = props.datasetId;

    // No dataset selected (e.g. right after a page refresh, before
    // any dataset is re-selected) - show the empty state instead of
    // falling back to the legacy no-id endpoint, which would return
    // whatever dataset the backend still has active in memory and
    // disagree with the sidebar/header, which already show "no
    // dataset loaded" in that case.
    if (!requestedDatasetId) {
        profile.value = null;
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

        const response = await getDatasetProfile(requestedDatasetId);

        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        profile.value = response;
    } catch (err) {
        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        console.error("Dataset profile error:", err);

        profile.value = null;

        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load dataset statistics.";
    } finally {
        if (requestedDatasetId === props.datasetId) {
            loading.value = false;
            refreshing.value = false;
        }
    }
}

const hasProfile = computed(() => Boolean(profile.value));

const rowCount = computed(() => {
    const value = Number(profile.value?.rows);
    return Number.isFinite(value) ? value.toLocaleString() : "—";
});

const columnCount = computed(() => {
    const value = Number(profile.value?.columns);
    return Number.isFinite(value) ? value.toLocaleString() : "—";
});

const duplicateRows = computed(() => {
    const value = Number(profile.value?.duplicate_rows);
    return Number.isFinite(value) ? value.toLocaleString() : "—";
});

const memoryUsage = computed(() => {
    const bytes = Number(profile.value?.memory_usage_bytes);

    if (!Number.isFinite(bytes) || bytes < 0) {
        return "0.00";
    }

    return (bytes / 1024 / 1024).toFixed(2);
});

const duplicatePercentage = computed(() => {
    const rows = Number(profile.value?.rows);
    const duplicates = Number(profile.value?.duplicate_rows);

    if (
        !Number.isFinite(rows) ||
        !Number.isFinite(duplicates) ||
        rows <= 0
    ) {
        return null;
    }

    return Math.min(
        Math.max((duplicates / rows) * 100, 0),
        100,
    ).toFixed(1);
});

const duplicateStatus = computed(() => {
    const percentage = Number(duplicatePercentage.value);

    if (!Number.isFinite(percentage) || percentage === 0) {
        return {
            label: "Clean",
            classes: "bg-emerald-50 text-emerald-700",
        };
    }

    if (percentage <= 5) {
        return {
            label: "Low",
            classes: "bg-amber-50 text-amber-700",
        };
    }

    return {
        label: "Review",
        classes: "bg-rose-50 text-rose-700",
    };
});

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return value ?? "—";
    }

    return new Intl.NumberFormat("en-US").format(number);
}

onMounted(() => {
    loadProfile();
});
</script>

<template>
    <section class="mt-4 w-full">
        <!-- =========================================================
             HEADER
        ========================================================== -->

        <div class="mb-4 flex items-center justify-between gap-4 max-[600px]:items-start">
            <div class="flex min-w-0 items-center gap-3">
                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 via-indigo-500 to-blue-500 text-white shadow-[0_6px_16px_rgba(99,102,241,0.20)]">
                    <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="1.9">
                        <rect x="3" y="3" width="18" height="18" rx="3" />
                        <path d="M8 8h8M8 12h8M8 16h5" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                        <h2 class="text-[17px] font-bold tracking-tight text-slate-900">
                            Dataset Overview
                        </h2>

                        <span v-if="hasProfile && !loading"
                            class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-700">
                            <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>

                            Ready
                        </span>
                    </div>

                    <p class="mt-0.5 text-[11px] text-slate-400">
                        Summary of your loaded dataset
                    </p>
                </div>
            </div>

            <!-- Refresh -->

            <button v-if="hasProfile && !loading" type="button" :disabled="refreshing"
                class="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] font-semibold text-slate-500 shadow-sm transition-all duration-200 hover:border-violet-200 hover:bg-violet-50 hover:text-violet-600 hover:shadow disabled:cursor-not-allowed disabled:opacity-60"
                @click="loadProfile({ refresh: true })">
                <svg class="h-3 w-3" :class="{
                    'animate-spin': refreshing,
                }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20 11a8.1 8.1 0 0 0-14.9-4" />
                    <path d="M4 4v5h5" />
                    <path d="M4 13a8.1 8.1 0 0 0 14.9 4" />
                    <path d="M20 20v-5h-5" />
                </svg>

                {{ refreshing ? "Refreshing..." : "Refresh" }}
            </button>
        </div>

        <!-- =========================================================
             LOADING
        ========================================================== -->

        <div v-if="loading" class="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <article v-for="index in 4" :key="index"
                class="rounded-xl border border-slate-100 bg-white p-4 shadow-[0_3px_12px_rgba(15,23,42,0.035)]">
                <div class="flex items-center gap-3">
                    <div class="h-10 w-10 animate-pulse rounded-xl bg-slate-100"></div>

                    <div class="min-w-0 flex-1">
                        <div class="h-2.5 w-14 animate-pulse rounded bg-slate-100"></div>

                        <div class="mt-2 h-5 w-20 animate-pulse rounded bg-slate-100"></div>
                    </div>
                </div>
            </article>
        </div>

        <!-- =========================================================
             ERROR
        ========================================================== -->

        <div v-else-if="error"
            class="flex items-center gap-3 rounded-xl border border-rose-100 bg-gradient-to-r from-rose-50 to-white px-4 py-3 max-[600px]:items-start">
            <div
                class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rose-100 text-xs font-bold text-rose-600">
                !
            </div>

            <div class="min-w-0 flex-1">
                <strong class="block text-[11px] font-bold text-slate-900">
                    Unable to load dataset overview
                </strong>

                <p class="mt-0.5 text-[10px] leading-4 text-slate-500">
                    {{ error }}
                </p>
            </div>

            <button type="button"
                class="shrink-0 rounded-lg bg-violet-600 px-2.5 py-1.5 text-[10px] font-semibold text-white shadow-sm transition hover:bg-violet-700"
                @click="loadProfile()">
                Retry
            </button>
        </div>

        <!-- =========================================================
             STATISTICS
        ========================================================== -->

        <div v-else-if="profile" class="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <!-- =====================================================
                 ROWS
            ====================================================== -->

            <article
                class="group relative overflow-hidden rounded-xl border border-violet-100 bg-gradient-to-br from-violet-50/80 via-white to-white p-4 shadow-[0_4px_14px_rgba(124,58,237,0.045)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_22px_rgba(124,58,237,0.10)]">
                <div
                    class="absolute -right-5 -top-5 h-16 w-16 rounded-full bg-violet-100/50 blur-xl transition group-hover:bg-violet-200/60">
                </div>

                <div class="relative flex items-center gap-3">
                    <div
                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
                        <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.9">
                            <path d="M7 3h10l4 4v14H7z" />
                            <path d="M7 7h14" />
                            <path d="M11 3v4" />
                            <path d="M11 11h6M11 15h6M11 19h4" />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span class="block text-[10px] font-semibold uppercase tracking-wide text-violet-400">
                            Rows
                        </span>

                        <strong class="mt-0.5 block truncate text-[21px] font-bold tracking-tight text-slate-900">
                            {{ rowCount }}
                        </strong>

                        <span class="text-[9px] text-slate-400">
                            Total records
                        </span>
                    </div>
                </div>
            </article>

            <!-- =====================================================
                 COLUMNS
            ====================================================== -->

            <article
                class="group relative overflow-hidden rounded-xl border border-blue-100 bg-gradient-to-br from-blue-50/80 via-white to-white p-4 shadow-[0_4px_14px_rgba(59,130,246,0.045)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_22px_rgba(59,130,246,0.10)]">
                <div
                    class="absolute -right-5 -top-5 h-16 w-16 rounded-full bg-blue-100/50 blur-xl transition group-hover:bg-blue-200/60">
                </div>

                <div class="relative flex items-center gap-3">
                    <div
                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
                        <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.9">
                            <rect x="3" y="4" width="18" height="16" rx="2" />
                            <path d="M3 10h18" />
                            <path d="M9 10v10" />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span class="block text-[10px] font-semibold uppercase tracking-wide text-blue-400">
                            Columns
                        </span>

                        <strong class="mt-0.5 block truncate text-[21px] font-bold tracking-tight text-slate-900">
                            {{ columnCount }}
                        </strong>

                        <span class="text-[9px] text-slate-400">
                            Total features
                        </span>
                    </div>
                </div>
            </article>

            <!-- =====================================================
                 DUPLICATES
            ====================================================== -->

            <article
                class="group relative overflow-hidden rounded-xl border border-emerald-100 bg-gradient-to-br from-emerald-50/80 via-white to-white p-4 shadow-[0_4px_14px_rgba(16,185,129,0.045)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_22px_rgba(16,185,129,0.10)]">
                <div
                    class="absolute -right-5 -top-5 h-16 w-16 rounded-full bg-emerald-100/50 blur-xl transition group-hover:bg-emerald-200/60">
                </div>

                <div class="relative flex items-center gap-3">
                    <div
                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
                        <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.9">
                            <path d="M8 8h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3z" />
                            <path d="M16 8V6a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3h2" />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span class="block text-[10px] font-semibold uppercase tracking-wide text-emerald-500">
                            Duplicates
                        </span>

                        <strong class="mt-0.5 block truncate text-[21px] font-bold tracking-tight text-slate-900">
                            {{ duplicateRows }}
                        </strong>

                        <span v-if="duplicatePercentage !== null" class="text-[9px] text-slate-400">
                            {{ duplicatePercentage }}% of records
                        </span>

                        <span v-else class="text-[9px] text-slate-400">
                            Duplicate rows
                        </span>
                    </div>
                </div>
            </article>

            <!-- =====================================================
                 MEMORY
            ====================================================== -->

            <article
                class="group relative overflow-hidden rounded-xl border border-orange-100 bg-gradient-to-br from-orange-50/80 via-white to-white p-4 shadow-[0_4px_14px_rgba(249,115,22,0.045)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_22px_rgba(249,115,22,0.10)]">
                <div
                    class="absolute -right-5 -top-5 h-16 w-16 rounded-full bg-orange-100/50 blur-xl transition group-hover:bg-orange-200/60">
                </div>

                <div class="relative flex items-center gap-3">
                    <div
                        class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-orange-100 text-orange-600">
                        <svg class="h-[19px] w-[19px]" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.9">
                            <rect x="6" y="6" width="12" height="12" rx="2" />
                            <path d="M9 1v5M15 1v5M9 18v5M15 18v5" />
                            <path d="M1 9h5M1 15h5M18 9h5M18 15h5" />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span class="block text-[10px] font-semibold uppercase tracking-wide text-orange-500">
                            Memory
                        </span>

                        <strong
                            class="mt-0.5 flex items-baseline gap-1 truncate text-[21px] font-bold tracking-tight text-slate-900">
                            {{ memoryUsage }}

                            <small class="text-[10px] font-semibold text-slate-500">
                                MB
                            </small>
                        </strong>

                        <span class="text-[9px] text-slate-400">
                            In memory
                        </span>
                    </div>
                </div>
            </article>
        </div>

        <!-- =========================================================
             NO DATASET SELECTED
        ========================================================== -->

        <div v-else
            class="flex min-h-[160px] flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-white px-5 text-center">
            <div class="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-400">
                <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                    <rect x="3" y="3" width="18" height="18" rx="3" />
                    <path d="M8 8h8M8 12h8M8 16h5" />
                </svg>
            </div>

            <h3 class="mt-3 text-[13px] font-bold text-slate-700">
                No dataset selected
            </h3>

            <p class="mt-1 max-w-xs text-[10px] leading-5 text-slate-400">
                Upload or select a dataset to see its overview.
            </p>
        </div>
    </section>
</template>