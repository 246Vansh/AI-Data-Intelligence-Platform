<script setup>
import { ref } from "vue";

import DatasetOverview from "./components/DatasetOverview.vue";
import AnalyticsBuilder from "./components/AnalyticsBuilder.vue";
import DataPreview from "./components/DataPreview.vue";
import DatasetUpload from "./components/DatasetUpload.vue";
import DatasetMetadata from "./components/DatasetMetadata.vue";

const refreshKey = ref(0);

function handleDatasetUploaded() {
    refreshKey.value += 1;
}

const selectedQuestion = ref("");

function handleQuestionSelected(question) {
    selectedQuestion.value = question;
}
</script>

<template>
    <div class="min-h-screen bg-[#f6f7fb] text-[#172033] selection:bg-violet-100 selection:text-violet-800">

        <!-- =====================================================
             SIDEBAR
        ====================================================== -->

        <aside class="fixed inset-y-0 left-0 z-40 hidden w-[210px] border-r border-slate-200/80 bg-white lg:block">

            <div class="flex h-full flex-col px-4 py-5">

                <!-- Brand -->

                <div class="mb-8 px-2">

                    <div class="flex items-center gap-3">

                        <div
                            class="relative grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-indigo-600 to-blue-600 text-lg font-bold text-white shadow-[0_8px_22px_rgba(99,102,241,0.25)]">

                            <span class="relative z-10">
                                ✦
                            </span>

                            <div class="absolute -right-2 -top-2 h-7 w-7 rounded-full bg-white/20 blur-sm">
                            </div>

                        </div>

                        <div class="min-w-0">

                            <p class="truncate text-[13px] font-bold tracking-[-0.2px] text-slate-900">
                                Data Intelligence
                            </p>

                            <p class="mt-0.5 text-[10px] font-medium text-slate-400">
                                AI Analytics Platform
                            </p>

                        </div>

                    </div>

                </div>

                <!-- Navigation Label -->

                <div class="mb-2 px-2 text-[9px] font-bold uppercase tracking-[0.7px] text-slate-400">
                    Workspace
                </div>

                <!-- Navigation -->

                <nav class="space-y-1">

                    <!-- Overview -->

                    <a href="#overview"
                        class="group relative flex items-center gap-3 rounded-xl bg-gradient-to-r from-violet-50 to-indigo-50 px-3 py-3 text-[12px] font-semibold text-violet-700">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-100 text-sm text-violet-600">
                            ⌂
                        </span>

                        <span>
                            Overview
                        </span>

                        <span class="ml-auto h-1.5 w-1.5 rounded-full bg-violet-500">
                        </span>

                    </a>

                    <!-- Ask Data -->

                    <a href="#ask-data"
                        class="group flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] font-medium text-slate-500 transition-all duration-200 hover:bg-violet-50 hover:text-violet-700">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-500 transition group-hover:bg-violet-100 group-hover:text-violet-600">
                            ✦
                        </span>

                        <span>
                            Ask Your Data
                        </span>

                    </a>

                    <!-- Data Preview -->

                    <a href="#data-preview"
                        class="group flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] font-medium text-slate-500 transition-all duration-200 hover:bg-blue-50 hover:text-blue-700">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-500 transition group-hover:bg-blue-100 group-hover:text-blue-600">
                            ▤
                        </span>

                        <span>
                            Data Preview
                        </span>

                    </a>

                    <!-- Schema -->

                    <a href="#dataset-schema"
                        class="group flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] font-medium text-slate-500 transition-all duration-200 hover:bg-emerald-50 hover:text-emerald-700">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-500 transition group-hover:bg-emerald-100 group-hover:text-emerald-600">
                            ▱
                        </span>

                        <span>
                            Dataset Schema
                        </span>

                    </a>

                    <!-- Insights -->

                    <a href="#insights"
                        class="group flex items-center gap-3 rounded-xl px-3 py-3 text-[12px] font-medium text-slate-500 transition-all duration-200 hover:bg-amber-50 hover:text-amber-700">

                        <span
                            class="flex h-7 w-7 items-center justify-center rounded-lg bg-slate-100 text-sm text-slate-500 transition group-hover:bg-amber-100 group-hover:text-amber-600">
                            ◈
                        </span>

                        <span>
                            Insights
                        </span>

                    </a>

                </nav>

                <!-- Divider -->

                <div class="my-6 border-t border-slate-100"></div>

                <!-- Dataset Status -->

                <div
                    class="rounded-2xl border border-emerald-100 bg-gradient-to-br from-emerald-50/80 to-teal-50/40 p-3.5">

                    <div class="flex items-center gap-2.5">

                        <div
                            class="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600">
                            ✓
                        </div>

                        <div>

                            <p class="text-[11px] font-bold text-emerald-800">
                                Dataset Ready
                            </p>

                            <p class="mt-0.5 text-[9px] text-emerald-600">
                                Analysis available
                            </p>

                        </div>

                    </div>

                </div>

                <!-- Help -->

                <div
                    class="mt-auto rounded-2xl border border-violet-100 bg-gradient-to-br from-violet-50 via-white to-indigo-50 p-4">

                    <div class="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
                        ?
                    </div>

                    <p class="text-[12px] font-bold text-slate-800">
                        Need help?
                    </p>

                    <p class="mt-1 text-[10px] leading-4 text-slate-400">
                        Learn how to get better insights from your data.
                    </p>

                    <button type="button"
                        class="mt-3 text-[11px] font-bold text-violet-600 transition hover:text-violet-800">
                        View documentation →
                    </button>

                </div>

            </div>

        </aside>

        <!-- =====================================================
             MAIN APPLICATION
        ====================================================== -->

        <div class="lg:pl-[210px]">

            <!-- =================================================
                 HEADER
            ================================================== -->

            <header class="sticky top-0 z-30 border-b border-slate-200/80 bg-white/85 backdrop-blur-xl">

                <div class="flex min-h-[70px] items-center justify-between px-5 sm:px-8 lg:px-10">

                    <!-- Brand -->

                    <div class="flex items-center gap-3">

                        <!-- Mobile logo -->

                        <div
                            class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 text-base font-bold text-white shadow-md lg:hidden">
                            ✦
                        </div>

                        <div>

                            <div class="flex items-center gap-2">

                                <h1 class="text-[14px] font-bold tracking-[-0.25px] text-slate-900 sm:text-[16px]">
                                    AI Data Intelligence Platform
                                </h1>

                                <span
                                    class="hidden rounded-full bg-violet-50 px-2 py-0.5 text-[8px] font-bold uppercase tracking-[0.5px] text-violet-600 sm:inline-block">
                                    Beta
                                </span>

                            </div>

                            <p class="mt-0.5 text-[10px] text-slate-400 sm:text-xs">
                                Interactive data analytics workspace
                            </p>

                        </div>

                    </div>

                    <!-- Header Actions -->

                    <div class="flex items-center gap-2 sm:gap-3">

                        <!-- Status -->

                        <div
                            class="flex items-center gap-2 rounded-full border border-emerald-100 bg-emerald-50 px-3 py-1.5 text-[10px] font-bold text-emerald-700 sm:px-3.5 sm:py-2 sm:text-xs">

                            <span class="relative flex h-2 w-2">

                                <span
                                    class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-50">
                                </span>

                                <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500">
                                </span>

                            </span>

                            <span class="hidden sm:inline">
                                Dataset Loaded
                            </span>

                            <span class="sm:hidden">
                                Ready
                            </span>

                        </div>

                        <!-- Theme -->

                        <button type="button"
                            class="hidden h-9 w-9 place-items-center rounded-xl border border-slate-200 bg-white text-sm text-slate-500 transition hover:border-violet-200 hover:bg-violet-50 hover:text-violet-600 sm:grid"
                            title="Theme">

                            ☾

                        </button>

                        <!-- Profile -->

                        <div
                            class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-slate-800 to-slate-950 text-[10px] font-bold text-white shadow-sm">
                            AI
                        </div>

                    </div>

                </div>

            </header>

            <!-- =================================================
                 CONTENT
            ================================================== -->

            <main class="mx-auto max-w-[1500px] px-5 pb-20 pt-7 sm:px-8 lg:px-10">

                <!-- =================================================
                     HERO
                ================================================== -->

                <section class="group relative mb-8 overflow-hidden rounded-[28px] border border-violet-100 bg-white">

                    <!-- Background -->

                    <div class="absolute inset-0 bg-gradient-to-br from-white via-violet-50/50 to-indigo-50/80">
                    </div>

                    <!-- Decorative glow -->

                    <div
                        class="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-violet-300/20 blur-3xl">
                    </div>

                    <div
                        class="pointer-events-none absolute -bottom-32 right-1/3 h-64 w-64 rounded-full bg-blue-300/15 blur-3xl">
                    </div>

                    <div
                        class="pointer-events-none absolute left-1/3 top-0 h-40 w-40 rounded-full bg-fuchsia-200/10 blur-3xl">
                    </div>

                    <!-- Content -->

                    <div class="relative z-10 flex min-h-[330px] items-center px-6 py-10 sm:px-8 lg:px-11 lg:py-12">

                        <div class="max-w-[720px]">

                            <!-- Badge -->

                            <div
                                class="mb-5 inline-flex items-center gap-2 rounded-full border border-violet-100 bg-white/90 px-3 py-1.5 text-[10px] font-bold text-violet-700 shadow-sm">

                                <span
                                    class="flex h-5 w-5 items-center justify-center rounded-full bg-violet-100 text-violet-600">
                                    ✦
                                </span>

                                AI-POWERED ANALYTICS

                            </div>

                            <!-- Heading -->

                            <h2
                                class="max-w-[760px] text-4xl font-extrabold leading-[1.02] tracking-[-2px] text-slate-950 sm:text-5xl lg:text-[58px]">

                                Turn your data into
                                <span
                                    class="bg-gradient-to-r from-violet-600 via-indigo-600 to-blue-600 bg-clip-text text-transparent">
                                    decisions.
                                </span>

                            </h2>

                            <!-- Description -->

                            <p
                                class="mt-5 max-w-[650px] text-[13px] leading-6 text-slate-500 sm:text-[15px] lg:text-[16px]">

                                Explore your dataset, understand its structure,
                                discover patterns, and ask questions using
                                natural language.

                            </p>

                            <!-- Small feature pills -->

                            <div class="mt-6 flex flex-wrap gap-2">

                                <span
                                    class="rounded-lg border border-violet-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-violet-700">
                                    Natural Language
                                </span>

                                <span
                                    class="rounded-lg border border-blue-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-blue-700">
                                    Smart Analytics
                                </span>

                                <span
                                    class="rounded-lg border border-emerald-100 bg-white/80 px-3 py-1.5 text-[10px] font-semibold text-emerald-700">
                                    Visual Insights
                                </span>

                            </div>

                        </div>

                        <!-- =================================================
                             HERO MINI ANALYTICS
                        ================================================== -->

                        <div
                            class="absolute right-8 top-1/2 hidden h-[205px] w-[300px] -translate-y-1/2 overflow-hidden rounded-[24px] border border-white/80 bg-white/80 p-5 shadow-[0_20px_50px_rgba(79,70,229,0.12)] backdrop-blur-md xl:block">

                            <!-- Header -->

                            <div class="mb-4 flex items-center justify-between">

                                <div>

                                    <p class="text-[9px] font-bold uppercase tracking-[0.5px] text-slate-400">
                                        Performance
                                    </p>

                                    <p class="mt-1 text-sm font-bold text-slate-800">
                                        Dataset Overview
                                    </p>

                                </div>

                                <div class="rounded-lg bg-emerald-50 px-2 py-1 text-[9px] font-bold text-emerald-600">
                                    +18.4%
                                </div>

                            </div>

                            <!-- Mini chart -->

                            <div class="flex h-[105px] items-end gap-2">

                                <div class="h-[34%] flex-1 rounded-t-md bg-gradient-to-t from-violet-500 to-violet-300">
                                </div>

                                <div class="h-[52%] flex-1 rounded-t-md bg-gradient-to-t from-indigo-500 to-indigo-300">
                                </div>

                                <div class="h-[43%] flex-1 rounded-t-md bg-gradient-to-t from-blue-500 to-blue-300">
                                </div>

                                <div class="h-[69%] flex-1 rounded-t-md bg-gradient-to-t from-violet-600 to-violet-300">
                                </div>

                                <div class="h-[83%] flex-1 rounded-t-md bg-gradient-to-t from-indigo-600 to-indigo-300">
                                </div>

                                <div class="h-[100%] flex-1 rounded-t-md bg-gradient-to-t from-blue-600 to-blue-300">
                                </div>

                            </div>

                            <!-- Bottom -->

                            <div class="mt-3 flex items-center justify-between border-t border-slate-100 pt-2">

                                <span class="text-[8px] text-slate-400">
                                    Data trend
                                </span>

                                <span class="flex items-center gap-1 text-[8px] font-semibold text-violet-600">
                                    <span class="h-1.5 w-1.5 rounded-full bg-violet-500"></span>
                                    AI analysis
                                </span>

                            </div>

                        </div>

                    </div>

                </section>

                <!-- =================================================
                     UPLOAD
                ================================================== -->

                <section id="upload" class="scroll-mt-24">
                    <DatasetUpload @dataset-uploaded="handleDatasetUploaded" />
                </section>

                <!-- =================================================
                     OVERVIEW
                ================================================== -->

                <section id="overview" class="scroll-mt-24 pt-8">

                    <DatasetOverview :key="`overview-${refreshKey}`" />

                </section>

                <!-- =================================================
                     DATA PREVIEW
                ================================================== -->

                <section id="data-preview" class="scroll-mt-24 pt-8">

                    <DataPreview :key="`preview-${refreshKey}`" />

                </section>

                <!-- =================================================
                     SCHEMA
                ================================================== -->

                <section id="dataset-schema" class="scroll-mt-24 pt-8">

                    <DatasetMetadata :key="`metadata-${refreshKey}`" @question-selected="handleQuestionSelected" />

                </section>

                <!-- =================================================
                     INSIGHTS
                ================================================== -->

                <section id="insights" class="scroll-mt-24 pt-4">
                </section>

                <!-- =================================================
                     ANALYTICS
                ================================================== -->

                <section id="ask-data" class="scroll-mt-24 pt-8">

                    <AnalyticsBuilder :key="`builder-${refreshKey}`" :incoming-question="selectedQuestion" />

                </section>

            </main>

        </div>

    </div>
</template>