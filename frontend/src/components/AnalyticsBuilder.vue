<script setup>
import { ref } from "vue";
import { analyzeDataset } from "../services/api";
import AnalyticsChart from "./AnalyticsChart.vue";
import AnalyticsInsights from "./AnalyticsInsights.vue";

const question = ref(
    "Show me the top 5 stores by average weekly sales during holidays."
);

const loading = ref(false);
const error = ref(null);
const result = ref(null);

async function analyze() {
    try {
        loading.value = true;
        error.value = null;
        result.value = null;

        const response = await analyzeDataset(question.value);

        if (!response.success) {
            error.value =
                response.error?.message ||
                "Unable to analyze the dataset.";
            return;
        }

        result.value = response;
    } catch (err) {
        console.error(err);

        error.value =
            err.response?.data?.detail ||
            "Unable to analyze dataset.";
    } finally {
        loading.value = false;
    }
}
</script>

<template>
    <section class="w-full">
        <!-- Ask Your Data -->
        <div
            class="rounded-[22px] border border-[#e7e5f2] bg-gradient-to-br from-white to-[#f9f7ff] p-7 shadow-[0_5px_15px_rgba(15,23,42,0.03),0_18px_45px_rgba(79,70,229,0.06)]"
        >
            <!-- Header -->
            <div
                class="mb-[26px] flex items-center justify-between gap-5 max-[700px]:flex-col max-[700px]:items-start"
            >
                <div class="flex items-center gap-[13px]">
                    <div
                        class="flex h-[42px] w-[42px] items-center justify-center rounded-xl bg-gradient-to-br from-[#ede9fe] to-[#e0e7ff] text-[#6d28d9]"
                    >
                        <svg
                            class="h-[22px] w-[22px]"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path
                                d="M21 11.5a8.38 8.38 0 0 1-9 8.3 8.5 8.5 0 0 1-3.7-.8L3 20l1.3-4.2A8.4 8.4 0 1 1 21 11.5Z"
                            />
                            <path d="M8 12h.01M12 12h.01M16 12h.01" />
                        </svg>
                    </div>

                    <div>
                        <h2 class="m-0 text-[21px] font-bold tracking-[-0.4px] text-[#172033]">
                            Ask Your Data
                        </h2>

                        <p class="mt-1 text-[13px] leading-normal text-[#7a8496]">
                            Ask a question in natural language and let AI
                            analyze your dataset.
                        </p>
                    </div>
                </div>

                <div
                    class="flex items-center gap-1.5 whitespace-nowrap rounded-full bg-[#f3efff] px-[11px] py-[7px] text-xs font-semibold text-[#6d28d9] max-[700px]:self-start"
                >
                    <span class="text-sm">✦</span>
                    AI Powered
                </div>
            </div>

            <!-- Question -->
            <div class="flex flex-col gap-[9px]">
                <label
                    for="question"
                    class="text-[13px] font-semibold text-[#344054]"
                >
                    What do you want to know?
                </label>

                <div class="relative">
                    <textarea
                        id="question"
                        v-model="question"
                        rows="4"
                        placeholder="Example: Show me the top 5 stores by average weekly sales during holidays."
                        :disabled="loading"
                        @keydown.ctrl.enter="analyze"
                        class="box-border min-h-[130px] w-full resize-y rounded-[15px] border border-[#d9d6e8] bg-white px-[17px] py-[17px] pr-12 text-sm leading-[1.6] text-[#172033] placeholder:text-[#a1a8b5] transition duration-200 focus:border-[#8b5cf6] focus:outline-none focus:ring-4 focus:ring-[#8b5cf6]/10 disabled:cursor-wait disabled:bg-[#f8f9fc]"
                    ></textarea>

                    <div
                        class="pointer-events-none absolute bottom-4 right-4 text-xl text-[#7c3aed]"
                    >
                        ✦
                    </div>
                </div>

                <div
                    class="mt-[5px] flex items-center justify-between gap-[15px] max-[700px]:flex-col max-[700px]:items-start"
                >
                    <span class="text-[11px] text-[#98a2b3]">
                        Press
                        <kbd
                            class="mx-0.5 inline-block rounded-[5px] border border-[#d9dce5] border-b-2 bg-white px-[5px] py-0.5 text-[10px] text-[#667085]"
                        >
                            Ctrl
                        </kbd>
                        +
                        <kbd
                            class="mx-0.5 inline-block rounded-[5px] border border-[#d9dce5] border-b-2 bg-white px-[5px] py-0.5 text-[10px] text-[#667085]"
                        >
                            Enter
                        </kbd>
                        to analyze
                    </span>

                    <button
                        class="flex min-w-[155px] items-center gap-[9px] rounded-[11px] border-0 bg-gradient-to-br from-[#7c3aed] to-[#6366f1] px-[17px] py-3 text-[13px] font-bold text-white shadow-[0_8px_18px_rgba(99,102,241,0.24)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_12px_24px_rgba(99,102,241,0.3)] active:translate-y-0 disabled:cursor-not-allowed disabled:opacity-55 disabled:shadow-none max-[700px]:w-full max-[700px]:justify-center"
                        :disabled="loading || !question.trim()"
                        @click="analyze"
                    >
                        <span
                            v-if="loading"
                            class="h-[15px] w-[15px] animate-spin rounded-full border-2 border-white/40 border-t-white"
                        ></span>

                        <svg
                            v-else
                            class="h-[18px] w-[18px]"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path
                                d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"
                            />
                            <path d="M19 16v5M21.5 18.5h-5" />
                        </svg>

                        <span>
                            {{ loading ? "Analyzing..." : "Analyze Data" }}
                        </span>

                        <span v-if="!loading" class="ml-auto text-[17px]">
                            →
                        </span>
                    </button>
                </div>
            </div>
        </div>

        <!-- Error -->
        <div
            v-if="error"
            class="mt-[18px] flex items-center gap-[13px] rounded-[14px] border border-red-200 bg-[#fffafa] px-[18px] py-4"
        >
            <div
                class="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-full bg-red-100 font-bold text-red-600"
            >
                !
            </div>

            <div>
                <strong class="mb-[3px] block text-[13px] text-red-800">
                    Analysis failed
                </strong>

                <p class="m-0 text-xs text-red-700">
                    {{ error }}
                </p>
            </div>
        </div>

        <!-- Result -->
<div
    v-if="result"
    class="mt-6 rounded-[20px] border border-[#e7e5f2] bg-white p-6 shadow-[0_5px_18px_rgba(15,23,42,0.04)] max-[700px]:mt-[18px]"
>
    <!-- Result Header -->
    <div
        class="mb-[22px] flex items-center justify-between gap-5 max-[700px]:flex-col max-[700px]:items-start"
    >
        <div class="flex items-start gap-3">
            <div
                class="flex h-[38px] w-[38px] shrink-0 items-center justify-center rounded-[11px] bg-emerald-50 text-lg font-bold text-emerald-600"
            >
                ✓
            </div>

            <div>
                <span
                    class="mb-[3px] block text-[11px] font-semibold uppercase tracking-[0.5px] text-[#7a8496]"
                >
                    Analysis Result
                </span>

                <h3
                    class="m-0 text-[19px] font-bold text-[#172033]"
                >
                    {{ result.visualization?.title }}
                </h3>

                <p class="mt-1 text-xs text-[#98a2b3]">
                    {{ result.data.row_count }} results returned.
                </p>
            </div>
        </div>

        <div
            class="whitespace-nowrap rounded-full bg-emerald-50 px-[11px] py-[7px] text-[11px] font-semibold text-emerald-700 max-[700px]:self-start"
        >
            Analysis Complete
        </div>
    </div>

    <!-- AI Insights -->
    <AnalyticsInsights
        v-if="result.insights?.insights?.length"
        :result="result"
    />

    <!-- Chart -->
    <div
        v-if="
            result.visualization &&
            result.visualization.type !== 'table'
        "
        class="w-full mt-4 rounded-[14px] border border-[#edf0f5] bg-[#fcfcfe] p-[18px]"
    >
        <AnalyticsChart :result="result" />
    </div>

    <!-- Table -->
    <div
        v-if="result.visualization?.type === 'table'"
        class="overflow-hidden rounded-[14px] border border-[#e8eaf1] bg-white"
    >
        <!-- Table Header -->
        <div
            class="flex items-center justify-between gap-[15px] border-b border-[#edf0f5] px-[18px] py-4"
        >
            <div>
                <h4 class="m-0 text-sm font-bold text-[#172033]">
                    Results
                </h4>

                <p class="mt-[3px] text-[11px] text-[#98a2b3]">
                    Data returned from your query
                </p>
            </div>

            <span
                class="whitespace-nowrap rounded-[7px] bg-[#f5f3ff] px-[9px] py-[5px] text-[11px] font-semibold text-[#6d28d9]"
            >
                {{ result.data.row_count }} rows
            </span>
        </div>

        <!-- Table -->
        <div class="w-full overflow-x-auto">
            <table class="min-w-[600px] w-full border-collapse">
                <thead>
                    <tr>
                        <th
                            v-for="column in result.data.columns"
                            :key="column"
                            class="whitespace-nowrap border-b border-[#edf0f5] bg-[#f8f9fc] px-4 py-[13px] text-left text-[11px] font-bold uppercase tracking-[0.35px] text-[#667085]"
                        >
                            {{ column }}
                        </th>
                    </tr>
                </thead>

                <tbody>
                    <tr
                        v-for="(row, index) in result.data.rows"
                        :key="index"
                        class="transition-colors duration-150 hover:bg-[#faf9ff]"
                    >
                        <td
                            v-for="column in result.data.columns"
                            :key="column"
                            class="whitespace-nowrap border-b border-[#edf0f5] px-4 py-[13px] text-left text-xs text-[#475467] last:border-b-0"
                        >
                            {{ row[column] }}
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
</div>
    </section>
</template>