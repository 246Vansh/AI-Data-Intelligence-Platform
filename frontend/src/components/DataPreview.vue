<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetPreview } from "../services/api";

const dataset = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);
const searchQuery = ref("");

async function loadPreview(options = {}) {
    const isRefresh = options.refresh === true;

    try {
        if (isRefresh) {
            refreshing.value = true;
        } else {
            loading.value = true;
        }

        error.value = null;

        dataset.value = await getDatasetPreview();
    } catch (err) {
        console.error("Dataset preview error:", err);

        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load the dataset preview.";
    } finally {
        loading.value = false;
        refreshing.value = false;
    }
}

const filteredRows = computed(() => {
    const rows = dataset.value?.rows || [];
    const query = searchQuery.value.trim().toLowerCase();

    if (!query) {
        return rows;
    }

    return rows.filter((row) =>
        Object.values(row).some((value) =>
            String(value ?? "")
                .toLowerCase()
                .includes(query)
        )
    );
});

const visibleRowCount = computed(() => filteredRows.value.length);

const totalRowCount = computed(() => dataset.value?.rows?.length || 0);

const columnCount = computed(() => dataset.value?.columns?.length || 0);

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

onMounted(() => {
    loadPreview();
});
</script>

<template>
    <section class="mt-10 w-full">
        <!-- ===================================================== -->
        <!-- SECTION HEADER -->
        <!-- ===================================================== -->

        <div
            class="mb-5 flex items-end justify-between gap-6 max-[760px]:items-start max-[760px]:flex-col"
        >
            <div class="flex items-start gap-3">
                <div
                    class="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#eff6ff] to-[#e0e7ff] text-[#2563eb] shadow-[0_5px_15px_rgba(37,99,235,0.08)]"
                >
                    <svg
                        class="h-[21px] w-[21px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect
                            x="3"
                            y="3"
                            width="18"
                            height="18"
                            rx="3"
                        />
                        <path d="M3 9h18" />
                        <path d="M9 9v12" />
                        <path d="M13 13h4" />
                        <path d="M13 17h4" />
                    </svg>
                </div>

                <div>
                    <div class="flex items-center gap-2">
                        <h2
                            class="m-0 text-xl font-bold tracking-[-0.35px] text-[#172033]"
                        >
                            Data Preview
                        </h2>

                        <span
                            v-if="dataset"
                            class="rounded-full bg-[#f5f3ff] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.3px] text-[#6d28d9]"
                        >
                            Live
                        </span>
                    </div>

                    <p class="mt-1 text-[13px] leading-5 text-[#7a8496]">
                        Inspect the records currently available to the
                        analytics engine.
                    </p>
                </div>
            </div>

            <!-- Refresh -->
            <button
                v-if="dataset"
                type="button"
                :disabled="refreshing"
                @click="loadPreview({ refresh: true })"
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
                    <path
                        d="M20 11a8.1 8.1 0 0 0-14.9-4"
                    />
                    <path d="M4 4v5h5" />
                    <path
                        d="M4 13a8.1 8.1 0 0 0 14.9 4"
                    />
                    <path d="M20 20v-5h-5" />
                </svg>

                {{ refreshing ? "Refreshing..." : "Refresh" }}
            </button>
        </div>

        <!-- ===================================================== -->
        <!-- LOADING STATE -->
        <!-- ===================================================== -->

        <div
            v-if="loading"
            class="overflow-hidden rounded-[18px] border border-[#e7e9f0] bg-white shadow-[0_5px_15px_rgba(15,23,42,0.03),0_14px_30px_rgba(15,23,42,0.04)]"
        >
            <div
                class="flex items-center justify-between border-b border-[#edf0f5] px-5 py-[18px]"
            >
                <div class="space-y-2">
                    <div
                        class="h-4 w-32 animate-pulse rounded bg-[#eef0f5]"
                    ></div>

                    <div
                        class="h-3 w-52 animate-pulse rounded bg-[#f2f3f7]"
                    ></div>
                </div>

                <div
                    class="h-7 w-20 animate-pulse rounded-lg bg-[#f3f1ff]"
                ></div>
            </div>

            <div class="overflow-hidden">
                <div
                    v-for="row in 7"
                    :key="row"
                    class="flex gap-5 border-b border-[#f0f1f5] px-5 py-4"
                >
                    <div
                        v-for="column in 6"
                        :key="column"
                        class="h-3 min-w-[100px] flex-1 animate-pulse rounded bg-[#f1f2f6]"
                    ></div>
                </div>
            </div>
        </div>

        <!-- ===================================================== -->
        <!-- ERROR STATE -->
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

                <div class="min-w-0">
                    <h3 class="m-0 text-sm font-bold text-[#172033]">
                        Unable to load dataset preview
                    </h3>

                    <p class="mt-1 text-[13px] leading-5 text-[#667085]">
                        {{ error }}
                    </p>

                    <button
                        type="button"
                        @click="loadPreview()"
                        class="mt-4 inline-flex items-center gap-2 rounded-lg bg-[#7c3aed] px-3.5 py-2 text-xs font-semibold text-white transition-colors duration-200 hover:bg-[#6d28d9]"
                    >
                        Try Again
                    </button>
                </div>
            </div>
        </div>

        <!-- ===================================================== -->
        <!-- DATASET -->
        <!-- ===================================================== -->

        <div
            v-else-if="dataset"
            class="overflow-hidden rounded-[18px] border border-[#e7e9f0] bg-white shadow-[0_5px_15px_rgba(15,23,42,0.03),0_14px_30px_rgba(15,23,42,0.04)]"
        >
            <!-- ================================================= -->
            <!-- TOOLBAR -->
            <!-- ================================================= -->

            <div
                class="flex items-center justify-between gap-5 border-b border-[#edf0f5] bg-gradient-to-b from-white to-[#fcfcfe] px-5 py-[17px] max-[760px]:flex-col max-[760px]:items-stretch"
            >
                <div>
                    <div class="flex items-center gap-2">
                        <h3 class="m-0 text-sm font-bold text-[#172033]">
                            Dataset Records
                        </h3>

                        <span
                            class="rounded-md bg-[#f8f9fc] px-2 py-1 text-[10px] font-semibold text-[#667085]"
                        >
                            {{ columnCount }} columns
                        </span>
                    </div>

                    <p class="mt-1 text-[11px] text-[#98a2b3]">
                        Showing
                        <strong class="font-semibold text-[#667085]">
                            {{ visibleRowCount }}
                        </strong>
                        of
                        <strong class="font-semibold text-[#667085]">
                            {{ totalRowCount }}
                        </strong>
                        preview records
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
                        placeholder="Search records..."
                        class="h-9 w-full rounded-lg border border-[#e4e7ec] bg-white pl-9 pr-9 text-xs text-[#172033] outline-none transition-all duration-200 placeholder:text-[#98a2b3] focus:border-[#a78bfa] focus:ring-2 focus:ring-[#ede9fe]"
                    />

                    <button
                        v-if="searchQuery"
                        type="button"
                        @click="clearSearch"
                        class="absolute right-2 top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-md text-[#98a2b3] transition-colors hover:bg-[#f2f4f7] hover:text-[#475467]"
                        aria-label="Clear search"
                    >
                        ×
                    </button>
                </div>
            </div>

            <!-- ================================================= -->
            <!-- EMPTY DATASET -->
            <!-- ================================================= -->

            <div
                v-if="!dataset.rows?.length"
                class="flex min-h-[240px] items-center justify-center px-6 text-center"
            >
                <div>
                    <div
                        class="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-[#f5f3ff] text-[#7c3aed]"
                    >
                        <svg
                            class="h-6 w-6"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="1.8"
                        >
                            <rect
                                x="3"
                                y="4"
                                width="18"
                                height="16"
                                rx="2"
                            />
                            <path d="M3 9h18" />
                        </svg>
                    </div>

                    <h3 class="mt-4 text-sm font-bold text-[#172033]">
                        No records available
                    </h3>

                    <p class="mt-1 text-xs text-[#98a2b3]">
                        The backend returned an empty dataset preview.
                    </p>
                </div>
            </div>

            <!-- ================================================= -->
            <!-- SEARCH EMPTY STATE -->
            <!-- ================================================= -->

            <div
                v-else-if="!filteredRows.length"
                class="flex min-h-[240px] items-center justify-center px-6 text-center"
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
                        No matching records
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
            <!-- TABLE -->
            <!-- ================================================= -->

            <div
                v-else
                class="w-full overflow-auto"
            >
                <table class="min-w-[900px] w-full border-collapse">
                    <thead>
                        <tr>
                            <th
                                v-for="(column, index) in dataset.columns"
                                :key="column"
                                class="sticky top-0 z-[2] whitespace-nowrap border-b border-[#e7e9f0] bg-[#fbfaff] px-[17px] py-[13px] text-left text-[10px] font-bold uppercase tracking-[0.45px] text-[#667085]"
                                :class="{
                                    'border-l border-[#edf0f5]':
                                        index > 0,
                                }"
                            >
                                <span
                                    class="inline-block max-w-[220px] overflow-hidden text-ellipsis align-middle"
                                    :title="column"
                                >
                                    {{ column }}
                                </span>
                            </th>
                        </tr>
                    </thead>

                    <tbody>
                        <tr
                            v-for="(row, rowIndex) in filteredRows"
                            :key="rowIndex"
                            class="group transition-colors duration-150 hover:bg-[#faf9ff]"
                        >
                            <td
                                v-for="column in dataset.columns"
                                :key="column"
                                class="max-w-[280px] whitespace-nowrap border-b border-[#edf0f5] px-[17px] py-[13px] text-left text-xs text-[#475467]"
                                :title="String(row[column] ?? '')"
                            >
                                {{ formatCell(row[column]) }}
                            </td>
                        </tr>
                    </tbody>
                </table>
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
                        Preview loaded successfully
                    </span>
                </div>

                <div class="flex items-center gap-4">
                    <span>
                        <strong class="font-semibold text-[#667085]">
                            {{ visibleRowCount }}
                        </strong>
                        visible
                    </span>

                    <span>
                        <strong class="font-semibold text-[#667085]">
                            {{ columnCount }}
                        </strong>
                        columns
                    </span>
                </div>
            </div>
        </div>
    </section>
</template>