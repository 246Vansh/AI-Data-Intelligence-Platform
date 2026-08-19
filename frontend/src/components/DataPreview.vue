<script setup>
import { onMounted, ref } from "vue";
import { getDatasetPreview } from "../services/api";

const dataset = ref(null);
const loading = ref(true);
const error = ref(null);

async function loadPreview() {
    try {
        loading.value = true;
        error.value = null;

        dataset.value = await getDatasetPreview();
    } catch (err) {
        console.error(err);
        error.value = "Unable to load dataset.";
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    loadPreview();
});
</script>

<template>
    <section class="mt-[30px] w-full">
        <!-- Header -->
        <div
            class="mb-[18px] flex items-center justify-between gap-5 max-[700px]:flex-col max-[700px]:items-start"
        >
            <div class="flex items-center gap-3">
                <div
                    class="flex h-10 w-10 items-center justify-center rounded-[11px] bg-gradient-to-br from-[#eff6ff] to-[#e0e7ff] text-[#2563eb]"
                >
                    <svg
                        class="h-[21px] w-[21px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect x="3" y="3" width="18" height="18" rx="3" />
                        <path d="M3 9h18" />
                        <path d="M9 9v12" />
                        <path d="M13 13h4" />
                        <path d="M13 17h4" />
                    </svg>
                </div>

                <div>
                    <h2
                        class="m-0 text-xl font-bold tracking-[-0.3px] text-[#172033]"
                    >
                        Data Preview
                    </h2>

                    <p class="mt-[3px] text-[13px] text-[#7a8496]">
                        Preview the records available in your dataset
                    </p>
                </div>
            </div>

            <div
                v-if="dataset"
                class="flex items-center gap-[7px] whitespace-nowrap rounded-full bg-[#ecfdf5] px-[11px] py-[7px] text-[11px] font-semibold text-[#047857]"
            >
                <span class="h-[7px] w-[7px] rounded-full bg-[#10b981]"></span>
                {{ dataset.rows.length }} records
            </div>
        </div>

        <!-- Loading -->
        <div
            v-if="loading"
            class="flex items-center gap-[14px] rounded-2xl border border-[#e8eaf1] bg-white px-6 py-[22px] text-[#667085]"
        >
            <div
                class="h-7 w-7 shrink-0 animate-spin rounded-full border-[3px] border-[#ede9fe] border-t-[#7c3aed]"
            ></div>

            <div>
                <strong
                    class="mb-1 block text-sm text-[#172033]"
                >
                    Loading dataset
                </strong>

                <p class="m-0 text-[13px]">
                    Preparing your data preview...
                </p>
            </div>
        </div>

        <!-- Error -->
        <div
            v-else-if="error"
            class="flex items-center gap-[13px] rounded-2xl border border-[#fecaca] bg-[#fffafa] px-6 py-[22px]"
        >
            <div
                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fee2e2] font-bold text-[#dc2626]"
            >
                !
            </div>

            <div>
                <strong
                    class="mb-1 block text-sm text-[#172033]"
                >
                    Unable to load dataset
                </strong>

                <p class="m-0 text-[13px] text-[#667085]">
                    {{ error }}
                </p>

                <button
                    type="button"
                    @click="loadPreview"
                    class="mt-[10px] rounded-lg border-0 bg-[#7c3aed] px-3 py-[7px] text-xs font-semibold text-white transition-colors duration-200 hover:bg-[#6d28d9]"
                >
                    Try Again
                </button>
            </div>
        </div>

        <!-- Dataset -->
        <div
            v-else-if="dataset"
            class="overflow-hidden rounded-[18px] border border-[#e7e9f0] bg-white shadow-[0_5px_15px_rgba(15,23,42,0.03),0_14px_30px_rgba(15,23,42,0.04)]"
        >
            <!-- Table Header -->
            <div
                class="flex items-center justify-between gap-5 border-b border-[#edf0f5] bg-gradient-to-b from-white to-[#fcfcfe] px-5 py-[18px] max-[700px]:items-start max-[700px]:flex-col"
            >
                <div>
                    <h3 class="m-0 text-sm font-bold text-[#172033]">
                        Dataset Records
                    </h3>

                    <p class="mt-1 text-[11px] text-[#98a2b3]">
                        Showing the available dataset preview
                    </p>
                </div>

                <div
                    class="whitespace-nowrap rounded-lg bg-[#f5f3ff] px-[10px] py-1.5 text-[11px] font-semibold text-[#6d28d9]"
                >
                    {{ dataset.columns.length }} columns
                </div>
            </div>

            <!-- Table -->
            <div class="w-full overflow-x-auto">
                <table class="min-w-[750px] w-full border-collapse">
                    <thead>
                        <tr>
                            <th
                                v-for="column in dataset.columns"
                                :key="column"
                                class="sticky top-0 z-[1] whitespace-nowrap border-b border-[#edf0f5] bg-[#fcf8ff] px-[17px] py-[13px] text-left text-[11px] font-bold uppercase tracking-[0.35px] text-black"
                            >
                                <span
                                    class="inline-flex max-w-[220px] items-center overflow-hidden text-ellipsis"
                                >
                                    {{ column }}
                                </span>
                            </th>
                        </tr>
                    </thead>

                    <tbody>
                        <tr
                            v-for="(row, index) in dataset.rows"
                            :key="index"
                            class="transition-colors duration-150 hover:bg-[#faf9ff]"
                        >
                            <td
                                v-for="column in dataset.columns"
                                :key="column"
                                class="whitespace-nowrap border-b border-[#edf0f5] px-[17px] py-[13px] text-left text-xs text-[#475467] last:border-b-0"
                            >
                                {{ row[column] }}
                            </td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- Footer -->
            <div
                class="flex items-center justify-between gap-[15px] border-t border-[#edf0f5] bg-[#fcfcfd] px-[18px] py-3 text-[11px] text-[#98a2b3] max-[700px]:items-start max-[700px]:flex-col"
            >
                <span>
                    Preview of
                    <strong class="font-semibold text-[#667085]">
                        {{ dataset.rows.length }}
                    </strong>
                    records
                </span>

                <span>
                    <strong class="font-semibold text-[#667085]">
                        {{ dataset.columns.length }}
                    </strong>
                    columns
                </span>
            </div>
        </div>
    </section>
</template>