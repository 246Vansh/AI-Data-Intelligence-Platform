<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetProfile } from "../services/api";

const profile = ref(null);
const loading = ref(true);
const error = ref(null);

const memoryUsage = computed(() => {
    const bytes = Number(profile.value?.memory_usage_bytes);

    if (!Number.isFinite(bytes) || bytes < 0) {
        return "0.00";
    }

    return (bytes / 1024 / 1024).toFixed(2);
});

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

const hasProfile = computed(() => {
    return Boolean(profile.value);
});

async function loadProfile() {
    loading.value = true;
    error.value = null;

    try {
        profile.value = await getDatasetProfile();
    } catch (err) {
        console.error("Failed to load dataset profile:", err);

        profile.value = null;
        error.value =
            err?.response?.data?.detail ||
            err?.response?.data?.message ||
            "Unable to load dataset statistics.";
    } finally {
        loading.value = false;
    }
}

onMounted(loadProfile);
</script>

<template>
    <section class="w-full">
        <!-- Section Header -->
        <div
            class="mb-5 flex items-end justify-between gap-4 max-[600px]:items-start"
        >
            <div class="flex items-center gap-3">
                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-[#ede9fe] to-[#e0e7ff] text-[#6d28d9]"
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
                        <path d="M8 8h8M8 12h8M8 16h5" />
                    </svg>
                </div>

                <div>
                    <h2
                        class="m-0 text-xl font-bold tracking-[-0.3px] text-[#172033]"
                    >
                        Dataset Overview
                    </h2>

                    <p class="mt-1 text-[13px] text-[#7a8496]">
                        Summary of your loaded dataset
                    </p>
                </div>
            </div>

            <div
                v-if="hasProfile && !loading"
                class="hidden items-center gap-2 rounded-full bg-[#ecfdf5] px-3 py-2 text-[11px] font-semibold text-[#047857] min-[601px]:flex"
            >
                <span
                    class="h-[7px] w-[7px] rounded-full bg-[#10b981] shadow-[0_0_0_3px_rgba(16,185,129,0.12)]"
                ></span>

                Dataset analyzed
            </div>
        </div>

        <!-- Loading State -->
        <div
            v-if="loading"
            class="grid grid-cols-1 gap-4 min-[601px]:grid-cols-2 min-[1101px]:grid-cols-4"
        >
            <article
                v-for="index in 4"
                :key="index"
                class="min-h-[138px] rounded-[18px] border border-[#e8eaf1] bg-white p-6"
            >
                <div class="flex items-start gap-4">
                    <div
                        class="h-[52px] w-[52px] shrink-0 animate-pulse rounded-[15px] bg-[#f2f3f7]"
                    ></div>

                    <div class="min-w-0 flex-1">
                        <div
                            class="h-4 w-20 animate-pulse rounded bg-[#f2f3f7]"
                        ></div>

                        <div
                            class="mt-4 h-8 w-24 animate-pulse rounded bg-[#f2f3f7]"
                        ></div>

                        <div
                            class="mt-3 h-3 w-28 animate-pulse rounded bg-[#f2f3f7]"
                        ></div>
                    </div>
                </div>
            </article>
        </div>

        <!-- Error State -->
        <div
            v-else-if="error"
            class="flex items-center gap-4 rounded-[18px] border border-[#fecaca] bg-[#fffafa] px-6 py-5"
        >
            <div
                class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#fee2e2] text-sm font-bold text-[#dc2626]"
            >
                !
            </div>

            <div class="min-w-0 flex-1">
                <strong class="block text-sm font-semibold text-[#172033]">
                    Unable to load dataset overview
                </strong>

                <p class="mt-1 text-[13px] leading-5 text-[#667085]">
                    {{ error }}
                </p>
            </div>

            <button
                type="button"
                class="shrink-0 rounded-lg bg-[#7c3aed] px-3 py-2 text-xs font-semibold text-white transition-all duration-200 hover:bg-[#6d28d9] hover:shadow-[0_5px_14px_rgba(124,58,237,0.22)] focus:outline-none focus:ring-2 focus:ring-[#c4b5fd] focus:ring-offset-2"
                @click="loadProfile"
            >
                Retry
            </button>
        </div>

        <!-- Dataset Statistics -->
        <div
            v-else-if="profile"
            class="grid grid-cols-1 gap-5 min-[601px]:grid-cols-2 min-[1101px]:grid-cols-4"
        >
            <!-- Rows -->
            <article
                class="group rounded-[18px] border border-[#e8eaf1] bg-white p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#ddd6fe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)]"
            >
                <div class="flex items-start gap-4">
                    <div
                        class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#f1edff] text-[#6d28d9]"
                    >
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
                        <span
                            class="block text-sm font-semibold text-[#667085]"
                        >
                            Rows
                        </span>

                        <strong
                            class="mt-1 block text-[30px] font-bold leading-tight tracking-[-0.8px] text-[#172033] max-[600px]:text-[27px]"
                        >
                            {{ rowCount }}
                        </strong>

                        <span class="mt-2 block text-xs text-[#98a2b3]">
                            Total records
                        </span>
                    </div>
                </div>
            </article>

            <!-- Columns -->
            <article
                class="group rounded-[18px] border border-[#e8eaf1] bg-white p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#bfdbfe] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)]"
            >
                <div class="flex items-start gap-4">
                    <div
                        class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#eff6ff] text-[#2563eb]"
                    >
                        <svg
                            class="h-[25px] w-[25px]"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <rect
                                x="3"
                                y="4"
                                width="18"
                                height="16"
                                rx="2"
                            />
                            <path d="M3 10h18" />
                            <path d="M9 10v10" />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span
                            class="block text-sm font-semibold text-[#667085]"
                        >
                            Columns
                        </span>

                        <strong
                            class="mt-1 block text-[30px] font-bold leading-tight tracking-[-0.8px] text-[#172033] max-[600px]:text-[27px]"
                        >
                            {{ columnCount }}
                        </strong>

                        <span class="mt-2 block text-xs text-[#98a2b3]">
                            Total features
                        </span>
                    </div>
                </div>
            </article>

            <!-- Duplicates -->
            <article
                class="group rounded-[18px] border border-[#e8eaf1] bg-white p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#a7f3d0] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)]"
            >
                <div class="flex items-start gap-4">
                    <div
                        class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#ecfdf5] text-[#059669]"
                    >
                        <svg
                            class="h-[25px] w-[25px]"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <path
                                d="M8 8h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3z"
                            />
                            <path
                                d="M16 8V6a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3h2"
                            />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span
                            class="block text-sm font-semibold text-[#667085]"
                        >
                            Duplicates
                        </span>

                        <strong
                            class="mt-1 block text-[30px] font-bold leading-tight tracking-[-0.8px] text-[#172033] max-[600px]:text-[27px]"
                        >
                            {{ duplicateRows }}
                        </strong>

                        <span class="mt-2 block text-xs text-[#98a2b3]">
                            Duplicate rows
                        </span>
                    </div>
                </div>
            </article>

            <!-- Memory -->
            <article
                class="group rounded-[18px] border border-[#e8eaf1] bg-white p-6 shadow-[0_4px_12px_rgba(15,23,42,0.03),0_12px_28px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-[3px] hover:border-[#fed7aa] hover:shadow-[0_8px_20px_rgba(15,23,42,0.06),0_18px_35px_rgba(15,23,42,0.07)]"
            >
                <div class="flex items-start gap-4">
                    <div
                        class="flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-[15px] bg-[#fff7ed] text-[#ea580c]"
                    >
                        <svg
                            class="h-[25px] w-[25px]"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            stroke-width="2"
                        >
                            <rect
                                x="6"
                                y="6"
                                width="12"
                                height="12"
                                rx="2"
                            />
                            <path
                                d="M9 1v5M15 1v5M9 18v5M15 18v5"
                            />
                            <path
                                d="M1 9h5M1 15h5M18 9h5M18 15h5"
                            />
                        </svg>
                    </div>

                    <div class="min-w-0">
                        <span
                            class="block text-sm font-semibold text-[#667085]"
                        >
                            Memory
                        </span>

                        <strong
                            class="mt-1 block text-[30px] font-bold leading-tight tracking-[-0.8px] text-[#172033] max-[600px]:text-[27px]"
                        >
                            {{ memoryUsage }}

                            <small
                                class="ml-1 text-base font-semibold tracking-normal text-[#667085]"
                            >
                                MB
                            </small>
                        </strong>

                        <span class="mt-2 block text-xs text-[#98a2b3]">
                            In memory
                        </span>
                    </div>
                </div>
            </article>
        </div>
    </section>
</template>