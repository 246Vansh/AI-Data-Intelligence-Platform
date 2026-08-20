<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetMetadata } from "../services/api";

const metadata = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);
const searchQuery = ref("");

async function loadMetadata(options = {}) {
    const isRefresh = options.refresh === true;

    try {
        if (isRefresh) {
            refreshing.value = true;
        } else {
            loading.value = true;
        }

        error.value = null;

        metadata.value = await getDatasetMetadata();
    } catch (err) {
        console.error("Dataset metadata error:", err);

        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load dataset metadata.";
    } finally {
        loading.value = false;
        refreshing.value = false;
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

    return columns.value.filter((column) => {
        return [
            column.name,
            column.role,
            column.data_type,
        ].some((value) =>
            String(value ?? "")
                .toLowerCase()
                .includes(query),
        );
    });
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

const totalMissingValues = computed(() => {
    return columns.value.reduce((total, column) => {
        const value = Number(column.missing_count);

        return total + (Number.isFinite(value) ? value : 0);
    }, 0);
});

const totalUniqueValues = computed(() => {
    return columns.value.reduce((total, column) => {
        const value = Number(column.unique_values);

        return total + (Number.isFinite(value) ? value : 0);
    }, 0);
});

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
        return "bg-blue-50 text-blue-700";
    }

    if (
        normalized.includes("dimension") ||
        normalized.includes("categor")
    ) {
        return "bg-violet-50 text-violet-700";
    }

    if (normalized.includes("date") || normalized.includes("time")) {
        return "bg-amber-50 text-amber-700";
    }

    if (normalized.includes("identifier") || normalized.includes("id")) {
        return "bg-slate-100 text-slate-700";
    }

    return "bg-emerald-50 text-emerald-700";
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
        <!-- ===================================================== -->
        <!-- HEADER -->
        <!-- ===================================================== -->

        <div
            class="mb-5 flex items-end justify-between gap-6 max-[760px]:items-start max-[760px]:flex-col"
        >
            <div class="flex items-start gap-3">
                <div
                    class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#f5f3ff] to-[#ede9fe] text-[#7c3aed] shadow-[0_5px_15px_rgba(124,58,237,0.08)]"
                >
                    <svg
                        class="h-[21px] w-[21px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path d="M4 5h16" />
                        <path d="M4 12h16" />
                        <path d="M4 19h16" />
                        <circle
                            cx="8"
                            cy="5"
                            r="1.5"
                        />
                        <circle
                            cx="16"
                            cy="12"
                            r="1.5"
                        />
                        <circle
                            cx="10"
                            cy="19"
                            r="1.5"
                        />
                    </svg>
                </div>

                <div>
                    <div class="flex items-center gap-2">
                        <h2
                            class="m-0 text-xl font-bold tracking-[-0.35px] text-[#172033]"
                        >
                            Dataset Schema
                        </h2>

                        <span
                            v-if="metadata"
                            class="rounded-full bg-[#ecfdf5] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.3px] text-[#047857]"
                        >
                            Ready
                        </span>
                    </div>

                    <p
                        class="mt-1 max-w-[620px] text-[13px] leading-5 text-[#7a8496]"
                    >
                        Understand the columns, data types, analytical roles,
                        and quality characteristics available to the data
                        engine.
                    </p>
                </div>
            </div>

            <!-- Refresh -->
            <button
                v-if="metadata"
                type="button"
                :disabled="refreshing"
                @click="loadMetadata({ refresh: true })"
                class="inline-flex items-center gap-2 rounded-lg border border-[#e4e7ec] bg-white px-3 py-2 text-xs font-semibold text-[#475467] shadow-[0_2px_6px_rgba(15,23,42,0.03)] transition-all duration-200 hover:border-[#c4b5fd] hover:bg-[#faf9ff] hover:text-[#6d28d9] disabled:cursor-not-allowed disabled:opacity-60"
            >
                <svg
                    class="h-3.5 w-3.5"
                    :class="{ 'animate-spin': refreshing }"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                >
                    <path d="M20 11a8.1 8.1 0 0 0-14.9-4" />
                    <path d="M4 4v5h5" />
                    <path d="M4 13a8.1 8.1 0 0 0 14.9 4" />
                    <path d="M20 20v-5h-5" />
                </svg>

                {{ refreshing ? "Refreshing..." : "Refresh" }}
            </button>
        </div>

        <!-- ===================================================== -->
        <!-- LOADING -->
        <!-- ===================================================== -->

        <div
            v-if="loading"
            class="overflow-hidden rounded-[18px] border border-[#e7e9f0] bg-white p-5 shadow-[0_5px_15px_rgba(15,23,42,0.03),0_14px_30px_rgba(15,23,42,0.04)]"
        >
            <div class="mb-5 flex items-center justify-between">
                <div class="space-y-2">
                    <div
                        class="h-4 w-36 animate-pulse rounded bg-[#eef0f5]"
                    ></div>

                    <div
                        class="h-3 w-56 animate-pulse rounded bg-[#f2f3f7]"
                    ></div>
                </div>

                <div
                    class="h-9 w-56 animate-pulse rounded-lg bg-[#f3f4f7]"
                ></div>
            </div>

            <div
                class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
            >
                <div
                    v-for="card in 6"
                    :key="card"
                    class="rounded-2xl border border-[#edf0f5] p-5"
                >
                    <div class="flex items-center justify-between">
                        <div
                            class="h-4 w-28 animate-pulse rounded bg-[#eef0f5]"
                        ></div>

                        <div
                            class="h-6 w-16 animate-pulse rounded-full bg-[#f3f1ff]"
                        ></div>
                    </div>

                    <div class="mt-5 space-y-3">
                        <div
                            class="h-3 w-24 animate-pulse rounded bg-[#f1f2f6]"
                        ></div>

                        <div
                            class="h-3 w-32 animate-pulse rounded bg-[#f1f2f6]"
                        ></div>

                        <div
                            class="h-3 w-28 animate-pulse rounded bg-[#f1f2f6]"
                        ></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ===================================================== -->
        <!-- ERROR -->
        <!-- ===================================================== -->

        <div
            v-else-if="error"
            class="rounded-[18px] border border-[#fecaca] bg-white p-6 shadow-[0_5px_15px_rgba(15,23,42,0.03)]"
        >
            <div class="flex items-start gap-4">
                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#fee2e2] text-sm font-bold text-[#dc2626]"
                >
                    !
                </div>

                <div>
                    <h3 class="m-0 text-sm font-bold text-[#172033]">
                        Unable to load dataset schema
                    </h3>

                    <p class="mt-1 text-[13px] leading-5 text-[#667085]">
                        {{ error }}
                    </p>

                    <button
                        type="button"
                        @click="loadMetadata()"
                        class="mt-4 rounded-lg bg-[#7c3aed] px-3.5 py-2 text-xs font-semibold text-white transition-colors duration-200 hover:bg-[#6d28d9]"
                    >
                        Try Again
                    </button>
                </div>
            </div>
        </div>

        <!-- ===================================================== -->
        <!-- METADATA -->
        <!-- ===================================================== -->

        <div
            v-else-if="metadata"
            class="overflow-hidden rounded-[18px] border border-[#e7e9f0] bg-white shadow-[0_5px_15px_rgba(15,23,42,0.03),0_14px_30px_rgba(15,23,42,0.04)]"
        >
            <!-- ================================================= -->
            <!-- SUMMARY -->
            <!-- ================================================= -->

            <div
                class="grid grid-cols-1 border-b border-[#edf0f5] sm:grid-cols-3"
            >
                <div
                    class="border-b border-[#edf0f5] px-5 py-4 sm:border-b-0 sm:border-r"
                >
                    <p
                        class="m-0 text-[10px] font-bold uppercase tracking-[0.5px] text-[#98a2b3]"
                    >
                        Columns
                    </p>

                    <p class="mt-1 text-xl font-bold text-[#172033]">
                        {{ formatNumber(columnCount) }}
                    </p>
                </div>

                <div
                    class="border-b border-[#edf0f5] px-5 py-4 sm:border-b-0 sm:border-r"
                >
                    <p
                        class="m-0 text-[10px] font-bold uppercase tracking-[0.5px] text-[#98a2b3]"
                    >
                        Unique Values
                    </p>

                    <p class="mt-1 text-xl font-bold text-[#172033]">
                        {{ formatNumber(totalUniqueValues) }}
                    </p>
                </div>

                <div class="px-5 py-4">
                    <p
                        class="m-0 text-[10px] font-bold uppercase tracking-[0.5px] text-[#98a2b3]"
                    >
                        Missing Values
                    </p>

                    <p
                        class="mt-1 text-xl font-bold"
                        :class="
                            totalMissingValues > 0
                                ? 'text-amber-600'
                                : 'text-emerald-600'
                        "
                    >
                        {{ formatNumber(totalMissingValues) }}
                    </p>
                </div>
            </div>

            <!-- ================================================= -->
            <!-- TOOLBAR -->
            <!-- ================================================= -->

            <div
                class="flex items-center justify-between gap-5 border-b border-[#edf0f5] bg-gradient-to-b from-white to-[#fcfcfe] px-5 py-[17px] max-[760px]:flex-col max-[760px]:items-stretch"
            >
                <div>
                    <h3 class="m-0 text-sm font-bold text-[#172033]">
                        Column Definitions
                    </h3>

                    <p class="mt-1 text-[11px] text-[#98a2b3]">
                        Showing
                        <strong class="font-semibold text-[#667085]">
                            {{ visibleColumnCount }}
                        </strong>
                        of
                        <strong class="font-semibold text-[#667085]">
                            {{ columnCount }}
                        </strong>
                        columns
                    </p>
                </div>

                <!-- Search -->
                <div class="relative w-[260px] max-w-full max-[760px]:w-full">
                    <svg
                        class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#98a2b3]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <circle
                            cx="11"
                            cy="11"
                            r="7"
                        />
                        <path d="m20 20-4-4" />
                    </svg>

                    <input
                        v-model="searchQuery"
                        type="search"
                        placeholder="Search columns..."
                        class="h-9 w-full rounded-lg border border-[#e4e7ec] bg-white pl-9 pr-9 text-xs text-[#172033] outline-none transition-all duration-200 placeholder:text-[#98a2b3] focus:border-[#a78bfa] focus:ring-2 focus:ring-[#ede9fe]"
                    />

                    <button
                        v-if="searchQuery"
                        type="button"
                        @click="clearSearch"
                        class="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-[#98a2b3] hover:bg-[#f2f4f7] hover:text-[#475467]"
                        aria-label="Clear search"
                    >
                        ×
                    </button>
                </div>
            </div>

            <!-- ================================================= -->
            <!-- ROLE SUMMARY -->
            <!-- ================================================= -->

            <div
                v-if="Object.keys(roleSummary).length"
                class="flex flex-wrap gap-2 border-b border-[#edf0f5] bg-[#fcfcfd] px-5 py-3"
            >
                <span
                    v-for="(count, role) in roleSummary"
                    :key="role"
                    class="inline-flex items-center gap-1.5 rounded-full border border-[#e8eaf0] bg-white px-2.5 py-1 text-[10px] font-semibold text-[#667085]"
                >
                    <span
                        class="h-1.5 w-1.5 rounded-full bg-[#7c3aed]"
                    ></span>

                    {{ normalizeRole(role) }}

                    <span class="text-[#98a2b3]">
                        {{ count }}
                    </span>
                </span>
            </div>

            <!-- ================================================= -->
            <!-- NO SEARCH RESULTS -->
            <!-- ================================================= -->

            <div
                v-if="!filteredColumns.length"
                class="flex min-h-[220px] items-center justify-center px-6 text-center"
            >
                <div>
                    <div
                        class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#f8f9fc] text-[#667085]"
                    >
                        <svg
                            class="h-6 w-6"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.8"
                        >
                            <circle
                                cx="11"
                                cy="11"
                                r="7"
                            />
                            <path d="m20 20-4-4" />
                        </svg>
                    </div>

                    <h3 class="mt-4 text-sm font-bold text-[#172033]">
                        No matching columns
                    </h3>

                    <p class="mt-1 text-xs text-[#98a2b3]">
                        Nothing matches "{{ searchQuery }}".
                    </p>

                    <button
                        type="button"
                        @click="clearSearch"
                        class="mt-4 rounded-lg border border-[#e4e7ec] bg-white px-3 py-2 text-xs font-semibold text-[#475467] hover:bg-[#f9fafb]"
                    >
                        Clear Search
                    </button>
                </div>
            </div>

            <!-- ================================================= -->
            <!-- COLUMN CARDS -->
            <!-- ================================================= -->

            <div
                v-else
                class="grid grid-cols-1 gap-4 bg-[#fafbfc] p-5 sm:grid-cols-2 lg:grid-cols-3"
            >
                <article
                    v-for="column in filteredColumns"
                    :key="column.name"
                    class="group rounded-2xl border border-[#e7e9f0] bg-white p-[18px] shadow-[0_3px_10px_rgba(15,23,42,0.025)] transition-all duration-200 hover:-translate-y-[1px] hover:border-[#ddd6fe] hover:shadow-[0_8px_22px_rgba(15,23,42,0.06)]"
                >
                    <!-- Card Header -->
                    <div
                        class="flex items-start justify-between gap-3"
                    >
                        <div class="min-w-0">
                            <h4
                                class="truncate text-sm font-bold text-[#172033]"
                                :title="column.name"
                            >
                                {{ column.name }}
                            </h4>

                            <p
                                class="mt-1 truncate text-[11px] text-[#98a2b3]"
                                :title="normalizeType(column.data_type)"
                            >
                                {{ normalizeType(column.data_type) }}
                            </p>
                        </div>

                        <span
                            class="shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold"
                            :class="roleClass(column.role)"
                        >
                            {{ normalizeRole(column.role) }}
                        </span>
                    </div>

                    <!-- Metrics -->
                    <div
                        class="mt-5 grid grid-cols-2 gap-2"
                    >
                        <div
                            class="rounded-xl bg-[#f8f9fc] px-3 py-2.5"
                        >
                            <p
                                class="m-0 text-[9px] font-bold uppercase tracking-[0.35px] text-[#98a2b3]"
                            >
                                Unique
                            </p>

                            <p
                                class="mt-1 text-sm font-bold text-[#344054]"
                            >
                                {{
                                    formatNumber(
                                        column.unique_values,
                                    )
                                }}
                            </p>
                        </div>

                        <div
                            class="rounded-xl px-3 py-2.5"
                            :class="
                                Number(column.missing_count) > 0
                                    ? 'bg-amber-50'
                                    : 'bg-emerald-50'
                            "
                        >
                            <p
                                class="m-0 text-[9px] font-bold uppercase tracking-[0.35px]"
                                :class="
                                    Number(column.missing_count) > 0
                                        ? 'text-amber-600'
                                        : 'text-emerald-600'
                                "
                            >
                                Missing
                            </p>

                            <p
                                class="mt-1 text-sm font-bold"
                                :class="
                                    Number(column.missing_count) > 0
                                        ? 'text-amber-700'
                                        : 'text-emerald-700'
                                "
                            >
                                {{
                                    formatNumber(
                                        column.missing_count,
                                    )
                                }}
                            </p>
                        </div>
                    </div>

                    <!-- Footer -->
                    <div
                        class="mt-4 flex items-center justify-between border-t border-[#f0f1f5] pt-3"
                    >
                        <span
                            class="text-[10px] font-medium text-[#98a2b3]"
                        >
                            Data type
                        </span>

                        <span
                            class="max-w-[150px] truncate text-[10px] font-semibold text-[#667085]"
                            :title="normalizeType(column.data_type)"
                        >
                            {{ normalizeType(column.data_type) }}
                        </span>
                    </div>
                </article>
            </div>

            <!-- ================================================= -->
            <!-- FOOTER -->
            <!-- ================================================= -->

            <div
                class="flex items-center justify-between gap-4 border-t border-[#edf0f5] bg-[#fcfcfd] px-[18px] py-3 text-[11px] text-[#98a2b3] max-[600px]:items-start max-[600px]:flex-col"
            >
                <div class="flex items-center gap-2">
                    <span
                        class="h-1.5 w-1.5 rounded-full bg-[#10b981]"
                    ></span>

                    <span>
                        Schema loaded successfully
                    </span>
                </div>

                <span>
                    {{ visibleColumnCount }} visible columns
                </span>
            </div>
        </div>
    </section>
</template>