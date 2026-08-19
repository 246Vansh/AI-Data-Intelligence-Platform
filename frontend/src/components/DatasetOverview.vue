<script setup>
import { onMounted, ref } from "vue";
import { getDatasetProfile } from "../services/api";

const profile = ref(null);
const loading = ref(true);
const error = ref(null);

async function loadProfile() {
    try {
        loading.value = true;
        error.value = null;

        profile.value = await getDatasetProfile();
    } catch (err) {
        console.error(err);
        error.value = "Unable to load dataset profile.";
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    loadProfile();
});
</script>

<template>
    <section class="w-full">
        <!-- Section Header -->
        <div class="mb-[18px]">
            <div class="flex items-center gap-3">
                <div class="flex h-[38px] w-[38px] items-center justify-center rounded-[11px] bg-gradient-to-br from-[#ede9fe] to-[#e0e7ff] text-[#6d28d9]">
                    <svg
                        class="h-5 w-5"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect x="3" y="3" width="18" height="18" rx="3" />
                        <path d="M8 8h8M8 12h8M8 16h5" />
                    </svg>
                </div>

                <div>
                    <h2 class="m-0 text-xl font-bold tracking-[-0.3px] text-[#172033]">
                        Dataset Overview
                    </h2>

                    <p class="mt-[3px] text-[13px] text-[#7a8496]">
                        Summary of your loaded dataset
                    </p>
                </div>
            </div>
        </div>

        <!-- Loading -->
        <div
            v-if="loading"
            class="flex items-center gap-[14px] rounded-2xl border border-[#e8eaf1] bg-white px-6 py-[22px] text-[#667085]"
        >
            <div class="h-7 w-7 shrink-0 animate-spin rounded-full border-[3px] border-[#ede9fe] border-t-[#7c3aed]"></div>

            <div>
                <strong class="mb-1 block text-sm text-[#172033]">
                    Loading dataset
                </strong>

                <p class="m-0 text-[13px]">
                    Preparing your dataset statistics...
                </p>
            </div>
        </div>

        <!-- Error -->
        <div
            v-else-if="error"
            class="flex items-center gap-[14px] rounded-2xl border border-[#fecaca] bg-[#fffafa] px-6 py-[22px] text-[#667085]"
        >
            <div class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fee2e2] font-bold text-[#dc2626]">
                !
            </div>

            <div>
                <strong class="mb-1 block text-sm text-[#172033]">
                    Unable to load dataset
                </strong>

                <p class="m-0 text-[13px]">
                    {{ error }}
                </p>

                <button
                    type="button"
                    @click="loadProfile"
                    class="mt-[10px] rounded-lg border-0 bg-[#7c3aed] px-3 py-[7px] text-xs font-semibold text-white transition-colors duration-200 hover:bg-[#6d28d9]"
                >
                    Try Again
                </button>
            </div>
        </div>

        <!-- Dataset Statistics -->
        <div
            v-else-if="profile"
            class="grid grid-cols-1 gap-5 min-[601px]:grid-cols-2 min-[1101px]:grid-cols-4"
        >
            <!-- Rows -->
            <article
                class="group flex min-h-[138px] items-start gap-4 rounded-[18px] border border-[#e8eaf1] bg-white/95 p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#ddd6fe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)] max-[600px]:min-h-[120px] max-[600px]:p-5"
            >
                <div class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#f1edff] text-[#6d28d9]">
                    <svg
                        class="h-[25px] w-[25px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path d="M7 3h10l4 4v14H7z" />
                        <path d="M7 7h14" />
                        <path d="M11 3v4" />
                        <path d="M11 11h6M11 15h6M11 19h4" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <span class="mb-[5px] block text-sm font-semibold text-[#667085]">
                        Rows
                    </span>

                    <strong class="block text-[30px] font-bold leading-[1.15] tracking-[-0.8px] text-[#172033] max-[600px]:text-[26px]">
                        {{ profile.rows.toLocaleString() }}
                    </strong>

                    <span class="mt-[7px] block text-xs text-[#98a2b3]">
                        Total records
                    </span>
                </div>
            </article>

            <!-- Columns -->
            <article
                class="group flex min-h-[138px] items-start gap-4 rounded-[18px] border border-[#e8eaf1] bg-white/95 p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#ddd6fe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)] max-[600px]:min-h-[120px] max-[600px]:p-5"
            >
                <div class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#eff6ff] text-[#2563eb]">
                    <svg
                        class="h-[25px] w-[25px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect x="3" y="4" width="18" height="16" rx="2" />
                        <path d="M3 10h18" />
                        <path d="M9 10v10" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <span class="mb-[5px] block text-sm font-semibold text-[#667085]">
                        Columns
                    </span>

                    <strong class="block text-[30px] font-bold leading-[1.15] tracking-[-0.8px] text-[#172033] max-[600px]:text-[26px]">
                        {{ profile.columns }}
                    </strong>

                    <span class="mt-[7px] block text-xs text-[#98a2b3]">
                        Total features
                    </span>
                </div>
            </article>

            <!-- Duplicates -->
            <article
                class="group flex min-h-[138px] items-start gap-4 rounded-[18px] border border-[#e8eaf1] bg-white/95 p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#ddd6fe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)] max-[600px]:min-h-[120px] max-[600px]:p-5"
            >
                <div class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#ecfdf5] text-[#059669]">
                    <svg
                        class="h-[25px] w-[25px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <path d="M8 8h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3z" />
                        <path d="M16 8V6a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3h2" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <span class="mb-[5px] block text-sm font-semibold text-[#667085]">
                        Duplicates
                    </span>

                    <strong class="block text-[30px] font-bold leading-[1.15] tracking-[-0.8px] text-[#172033] max-[600px]:text-[26px]">
                        {{ profile.duplicate_rows }}
                    </strong>

                    <span class="mt-[7px] block text-xs text-[#98a2b3]">
                        Duplicate rows
                    </span>
                </div>
            </article>

            <!-- Memory -->
            <article
                class="group flex min-h-[138px] items-start gap-4 rounded-[18px] border border-[#e8eaf1] bg-white/95 p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#ddd6fe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)] max-[600px]:min-h-[120px] max-[600px]:p-5"
            >
                <div class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#fff7ed] text-[#ea580c]">
                    <svg
                        class="h-[25px] w-[25px]"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                    >
                        <rect x="6" y="6" width="12" height="12" rx="2" />
                        <path d="M9 1v5M15 1v5M9 18v5M15 18v5" />
                        <path d="M1 9h5M1 15h5M18 9h5M18 15h5" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <span class="mb-[5px] block text-sm font-semibold text-[#667085]">
                        Memory
                    </span>

                    <strong class="block text-[30px] font-bold leading-[1.15] tracking-[-0.8px] text-[#172033] max-[600px]:text-[26px]">
                        {{
                            (
                                profile.memory_usage_bytes /
                                1024 /
                                1024
                            ).toFixed(2)
                        }}
                        <small class="text-base font-semibold tracking-normal text-[#667085]">
                            MB
                        </small>
                    </strong>

                    <span class="mt-[7px] block text-xs text-[#98a2b3]">
                        In memory
                    </span>
                </div>
            </article>
        </div>
    </section>
</template>