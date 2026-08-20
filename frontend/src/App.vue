<script setup>
import DatasetOverview from "./components/DatasetOverview.vue";
import AnalyticsBuilder from "./components/AnalyticsBuilder.vue";
import DataPreview from "./components/DataPreview.vue";
</script>

<template>
    <div
        class="min-h-screen bg-[#f8f9ff] bg-[radial-gradient(circle_at_85%_10%,rgba(124,58,237,0.08),transparent_30%)] text-[#172033]"
    >
        <!-- Header -->
        <header class="border-b border-[#e8eaf0] bg-white/90 backdrop-blur-[12px]">
            <div
                class="mx-auto flex min-h-[76px] w-[calc(100%-64px)] max-w-[1400px] items-center justify-between max-[900px]:w-[calc(100%-32px)] max-[900px]:max-w-[700px] max-[600px]:min-h-[68px]"
            >
                <!-- Brand -->
                <div class="flex items-center gap-[14px]">
                    <div
                        class="grid h-[42px] w-[42px] place-items-center rounded-xl bg-gradient-to-br from-[#7c3aed] to-[#4f46e5] text-[22px] text-white shadow-[0_8px_20px_rgba(99,102,241,0.25)]"
                    >
                        ✦
                    </div>

                    <div>
                        <h1 class="m-0 text-xl font-bold text-[#172033]">
                            AI Data Intelligence Platform
                        </h1>

                        <p class="mt-[3px] text-[13px] text-[#697386]">
                            Interactive data analytics dashboard
                        </p>
                    </div>
                </div>

                <!-- Status -->
                <div
                    class="flex items-center gap-2 rounded-full bg-[#ecfdf5] px-[14px] py-[9px] text-[13px] font-semibold text-[#047857] max-[600px]:hidden"
                >
                    <span class="h-2 w-2 rounded-full bg-[#10b981]"></span>
                    Dataset Loaded
                </div>
            </div>
        </header>

        <!-- Main -->
        <main
            class="mx-auto w-[calc(100%-64px)] max-w-[1400px] pb-[60px] pt-11 max-[900px]:w-[calc(100%-32px)] max-[900px]:max-w-[700px] max-[600px]:pt-7"
        >
            <!-- Hero -->
            <section
                class="mb-[34px] flex min-h-[220px] items-center justify-between gap-10 max-[900px]:min-h-0"
            >
                <div>
                    <h2
                        class="m-0 max-w-[800px] text-[clamp(36px,4vw,58px)] font-bold leading-[1.05] tracking-[-1.8px] text-[#111827] max-[600px]:text-[36px]"
                    >
                        AI Data Intelligence Platform
                    </h2>

                    <p
                        class="mt-4 max-w-[650px] text-[17px] leading-[1.6] text-[#667085] max-[600px]:text-[15px]"
                    >
                        Explore your dataset, understand its structure, and ask
                        questions using natural language.
                    </p>
                </div>

                <!-- Hero Visual -->
                <div
                    class="flex h-[150px] w-[220px] shrink-0 items-end justify-center gap-3 rounded-3xl border border-[rgba(124,58,237,0.1)] bg-gradient-to-br from-[rgba(124,58,237,0.12)] to-[rgba(59,130,246,0.08)] p-5 max-[900px]:hidden"
                >
                    <div
                        class="h-[45px] w-7 rounded-[8px_8px_3px_3px] bg-gradient-to-b from-[#8b5cf6] to-[#6366f1]"
                    ></div>

                    <div
                        class="h-[75px] w-7 rounded-[8px_8px_3px_3px] bg-gradient-to-b from-[#8b5cf6] to-[#6366f1]"
                    ></div>

                    <div
                        class="h-[100px] w-7 rounded-[8px_8px_3px_3px] bg-gradient-to-b from-[#8b5cf6] to-[#6366f1]"
                    ></div>

                    <div
                        class="h-[125px] w-7 rounded-[8px_8px_3px_3px] bg-gradient-to-b from-[#8b5cf6] to-[#6366f1]"
                    ></div>
                </div>
            </section>

            <!-- Dataset Overview -->
            <DatasetOverview />

            <!-- Data Preview -->
            <DataPreview />

            <!-- Analytics -->
            <section class="mt-10">
                <AnalyticsBuilder />
            </section>
        </main>
    </div>
</template>