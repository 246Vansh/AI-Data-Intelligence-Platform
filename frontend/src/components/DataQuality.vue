<script setup>
import { ref, computed, onMounted } from "vue";
import { getDatasetQuality, getApiErrorMessage } from "../services/api";

const loading = ref(true);
const error = ref(null);
const qualityData = ref(null);
const activeFilter = ref("all");

const statusColor = computed(() => {
    const status = qualityData.value?.status;
    if (status === "healthy") return "emerald";
    if (status === "info") return "blue";
    if (status === "warning") return "amber";
    return "rose";
});

const healthScore = computed(() => {
    if (!qualityData.value) return 100;
    const issues = qualityData.value.issues || [];
    if (issues.length === 0) return 100;

    let penalty = 0;
    for (const issue of issues) {
        if (issue.severity === "error") penalty += 25;
        else if (issue.severity === "warning") penalty += 10;
        else penalty += 3;
    }
    return Math.max(0, Math.min(100, 100 - penalty));
});

const missingCount = computed(() => {
    return qualityData.value?.issues
        ?.filter((i) => i.type === "missing_values")
        .reduce((sum, i) => sum + (i.count || 0), 0) || 0;
});

const duplicateCount = computed(() => {
    return qualityData.value?.issues
        ?.find((i) => i.type === "duplicate_rows")?.count || 0;
});

const outlierCount = computed(() => {
    return qualityData.value?.issues
        ?.filter((i) => i.type === "numeric_outliers")
        .reduce((sum, i) => sum + (i.count || 0), 0) || 0;
});

const filteredIssues = computed(() => {
    if (!qualityData.value?.issues) return [];
    if (activeFilter.value === "all") return qualityData.value.issues;
    return qualityData.value.issues.filter(
        (i) => i.severity === activeFilter.value
    );
});

async function fetchQuality() {
    loading.value = true;
    error.value = null;

    try {
        const data = await getDatasetQuality();
        qualityData.value = data;
    } catch (err) {
        error.value = getApiErrorMessage(err);
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    fetchQuality();
});
</script>

<template>
    <div class="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm">
        <!-- Header -->
        <div class="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-5">
            <div>
                <div class="flex items-center gap-2.5">
                    <div class="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100 text-violet-700">
                        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                                d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                        </svg>
                    </div>
                    <div>
                        <h3 class="text-base font-bold text-slate-800">
                            Data Quality & Hygiene Audit
                        </h3>
                        <p class="text-xs text-slate-500">
                            Automated integrity, anomaly, and distribution analysis
                        </p>
                    </div>
                </div>
            </div>

            <button @click="fetchQuality"
                class="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:bg-slate-100">
                <svg class="h-3.5 w-3.5" :class="{ 'animate-spin': loading }" fill="none" viewBox="0 0 24 24"
                    stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                        d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Refresh Audit
            </button>
        </div>

        <!-- Loading State -->
        <div v-if="loading" class="flex h-48 items-center justify-center">
            <div class="flex flex-col items-center gap-2">
                <div class="h-7 w-7 animate-spin rounded-full border-2 border-violet-600 border-t-transparent"></div>
                <span class="text-xs font-medium text-slate-500">Auditing dataset quality...</span>
            </div>
        </div>

        <!-- Error State -->
        <div v-else-if="error" class="rounded-xl border border-rose-200 bg-rose-50/50 p-4 text-xs text-rose-700">
            {{ error }}
        </div>

        <!-- Main Content -->
        <div v-else class="space-y-6">
            <!-- Top Summary Cards -->
            <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <!-- Health Score Card -->
                <div class="rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Health Score</span>
                    <div class="mt-2 flex items-baseline gap-2">
                        <span class="text-2xl font-black" :class="healthScore >= 80
                            ? 'text-emerald-600'
                            : healthScore >= 60
                                ? 'text-amber-600'
                                : 'text-rose-600'
                            ">
                            {{ healthScore }}%
                        </span>
                        <span class="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase" :class="healthScore >= 80
                            ? 'bg-emerald-100 text-emerald-700'
                            : healthScore >= 60
                                ? 'bg-amber-100 text-amber-700'
                                : 'bg-rose-100 text-rose-700'
                            ">
                            {{ qualityData?.status }}
                        </span>
                    </div>
                </div>

                <!-- Missing Values Card -->
                <div class="rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Missing Values</span>
                    <div class="mt-2 text-2xl font-black text-slate-800">
                        {{ missingCount.toLocaleString() }}
                    </div>
                    <span class="text-[10px] text-slate-500">
                        {{ missingCount === 0 ? "Zero null values" : "Requires attention" }}
                    </span>
                </div>

                <!-- Duplicates Card -->
                <div class="rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">Duplicate Rows</span>
                    <div class="mt-2 text-2xl font-black text-slate-800">
                        {{ duplicateCount.toLocaleString() }}
                    </div>
                    <span class="text-[10px] text-slate-500">
                        {{ duplicateCount === 0 ? "Unique rows" : "Duplicate records" }}
                    </span>
                </div>

                <!-- Outliers Card -->
                <div class="rounded-xl border border-slate-100 bg-gradient-to-br from-slate-50 to-white p-4 shadow-sm">
                    <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-400">IQR Outliers</span>
                    <div class="mt-2 text-2xl font-black text-slate-800">
                        {{ outlierCount.toLocaleString() }}
                    </div>
                    <span class="text-[10px] text-slate-500">
                        {{ outlierCount === 0 ? "Normal distribution" : "Statistical outliers" }}
                    </span>
                </div>
            </div>

            <!-- Issues Filter & Details Table -->
            <div class="rounded-xl border border-slate-100 bg-white">
                <!-- Filter Tabs -->
                <div class="flex items-center justify-between border-b border-slate-100 px-4 py-3">
                    <div class="flex items-center gap-1.5">
                        <button @click="activeFilter = 'all'" :class="activeFilter === 'all'
                            ? 'bg-slate-900 text-white'
                            : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                            " class="rounded-lg px-2.5 py-1 text-xs font-semibold transition">
                            All ({{ qualityData?.issues?.length || 0 }})
                        </button>
                        <button @click="activeFilter = 'warning'" :class="activeFilter === 'warning'
                            ? 'bg-amber-600 text-white'
                            : 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                            " class="rounded-lg px-2.5 py-1 text-xs font-semibold transition">
                            Warnings
                        </button>
                        <button @click="activeFilter = 'info'" :class="activeFilter === 'info'
                            ? 'bg-blue-600 text-white'
                            : 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                            " class="rounded-lg px-2.5 py-1 text-xs font-semibold transition">
                            Info
                        </button>
                    </div>

                    <span class="text-xs font-medium text-slate-400">
                        Showing {{ filteredIssues.length }} items
                    </span>
                </div>

                <!-- Issues Table / List -->
                <div v-if="filteredIssues.length === 0" class="p-8 text-center">
                    <div class="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
                        <svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                    <h4 class="mt-2 text-xs font-bold text-slate-700">No issues found in this category</h4>
                    <p class="text-[11px] text-slate-500">Your dataset passes all corresponding validation checks.</p>
                </div>

                <div v-else class="divide-y divide-slate-100">
                    <div v-for="(issue, index) in filteredIssues" :key="index"
                        class="flex flex-wrap items-center justify-between gap-3 px-4 py-3.5 transition hover:bg-slate-50/70">
                        <div class="flex items-start gap-3">
                            <span class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                                :class="issue.severity === 'error'
                                    ? 'bg-rose-100 text-rose-700'
                                    : issue.severity === 'warning'
                                        ? 'bg-amber-100 text-amber-700'
                                        : 'bg-blue-100 text-blue-700'
                                    ">
                                !
                            </span>
                            <div>
                                <p class="text-xs font-semibold text-slate-800">
                                    {{ issue.message }}
                                </p>
                                <div class="mt-1 flex items-center gap-2 text-[10px] text-slate-400">
                                    <span v-if="issue.column" class="font-mono bg-slate-100 px-1.5 py-0.5 rounded text-slate-600">
                                        column: {{ issue.column }}
                                    </span>
                                    <span>type: {{ issue.type }}</span>
                                </div>
                            </div>
                        </div>

                        <span class="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider"
                            :class="issue.severity === 'error'
                                ? 'bg-rose-100 text-rose-700'
                                : issue.severity === 'warning'
                                    ? 'bg-amber-100 text-amber-700'
                                    : 'bg-blue-100 text-blue-700'
                                ">
                            {{ issue.severity }}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>
