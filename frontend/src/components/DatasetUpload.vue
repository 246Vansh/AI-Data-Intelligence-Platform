<script setup>
import { computed, ref } from "vue";
import { uploadDataset, getApiErrorMessage } from "../services/api";

const emit = defineEmits(["dataset-uploaded"]);

const props = defineProps({
    // The dataset store's currently selected/primary dataset (see
    // Dashboard.vue's `selectedDataset`) - reused here instead of an
    // independent fetch so this card never disagrees with the
    // sidebar/header about what's actually active.
    activeDataset: {
        type: Object,
        default: null,
    },
});

const fileInput = ref(null);
const selectedFile = ref(null);

const loading = ref(false);
const isDragging = ref(false);
const error = ref(null);
const success = ref(null);

const allowedExtensions = [".csv"];

const hasDataset = computed(() => Boolean(props.activeDataset));

const fileSize = computed(() => {
    if (!selectedFile.value) {
        return "";
    }

    const bytes = selectedFile.value.size;

    if (bytes < 1024) {
        return `${bytes} B`;
    }

    if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
    }

    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
});

const fileExtension = computed(() => {
    if (!selectedFile.value?.name) {
        return "";
    }

    const parts = selectedFile.value.name.split(".");

    return parts.length > 1
        ? `.${parts.pop().toLowerCase()}`
        : "";
});

function isValidFile(file) {
    if (!file) {
        return false;
    }

    const extension = file.name
        .slice(file.name.lastIndexOf("."))
        .toLowerCase();

    return allowedExtensions.includes(extension);
}

function selectFile(file) {
    error.value = null;
    success.value = null;

    if (!file) {
        return;
    }

    if (!isValidFile(file)) {
        selectedFile.value = null;

        error.value =
            "Unsupported file type. Please upload a CSV file.";

        return;
    }

    selectedFile.value = file;
}

function openFilePicker() {
    fileInput.value?.click();
}

function handleFileChange(event) {
    const file = event.target.files?.[0];

    selectFile(file);

    event.target.value = "";
}

function handleDrop(event) {
    isDragging.value = false;

    const file = event.dataTransfer?.files?.[0];

    selectFile(file);
}

function removeSelectedFile() {
    selectedFile.value = null;
    error.value = null;
    success.value = null;
}

async function handleUpload() {
    if (!selectedFile.value || loading.value) {
        return;
    }

    loading.value = true;
    error.value = null;
    success.value = null;

    try {
        const response = await uploadDataset(
            selectedFile.value,
        );

        // The "Active Dataset" card below reads from `activeDataset`
        // (the dataset store's selection, via Dashboard.vue) instead
        // of local state - it updates once the parent selects this
        // upload's dataset_id in response to the emit below.

        success.value =
            "Dataset uploaded successfully and is now active.";

        selectedFile.value = null;

        emit("dataset-uploaded", response);
    } catch (err) {
        console.error("Dataset upload error:", err);

        error.value =
            getApiErrorMessage(err) ||
            "Unable to upload the dataset.";
    } finally {
        loading.value = false;
    }
}

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return "—";
    }

    return number.toLocaleString();
}
</script>

<template>
    <section class="w-full">

        <!-- =====================================================
             SECTION HEADER
        ====================================================== -->

        <div class="mb-4 flex items-center justify-between gap-4">
            <div class="flex min-w-0 items-center gap-3">

                <!-- Icon -->
                <div
                    class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 via-indigo-500 to-cyan-500 text-white shadow-[0_6px_16px_rgba(99,102,241,0.20)]">
                    <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9">
                        <path d="M12 16V4" />
                        <path d="m7 9 5-5 5 5" />
                        <path d="M5 20h14" />
                    </svg>
                </div>

                <div class="min-w-0">
                    <div class="flex items-center gap-2">
                        <h2 class="truncate text-[17px] font-bold tracking-[-0.25px] text-slate-900">
                            Upload Dataset
                        </h2>

                        <span v-if="hasDataset"
                            class="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-1 text-[9px] font-bold text-emerald-700">
                            <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                            Active
                        </span>
                    </div>

                    <p class="mt-0.5 text-[11px] leading-4 text-slate-500">
                        Upload a CSV to power your analytics workspace.
                    </p>
                </div>
            </div>

            <!-- CSV Badge -->
            <div
                class="hidden shrink-0 items-center gap-1.5 rounded-full border border-cyan-100 bg-cyan-50 px-2.5 py-1.5 text-[9px] font-bold text-cyan-700 sm:flex">
                <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M4 4h16v16H4z" />
                    <path d="M8 8h8M8 12h8M8 16h5" />
                </svg>

                CSV Dataset
            </div>
        </div>


        <!-- =====================================================
             MAIN CARD
        ====================================================== -->

        <div
            class="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-[0_5px_18px_rgba(15,23,42,0.04)]">

            <div class="p-3.5 sm:p-4">

                <!-- Hidden File Input -->
                <input ref="fileInput" type="file" accept=".csv" class="hidden" @change="handleFileChange" />


                <!-- =================================================
                     DROPZONE
                ================================================== -->

                <div class="group relative flex min-h-[82px] cursor-pointer items-center gap-4 overflow-hidden rounded-xl border border-dashed px-4 py-4 text-left transition-all duration-200 max-[500px]:flex-col max-[500px]:text-center"
                    :class="isDragging
                        ? 'border-violet-500 bg-gradient-to-r from-violet-50 to-indigo-50 shadow-[0_0_0_3px_rgba(124,58,237,0.06)]'
                        : 'border-violet-200 bg-gradient-to-r from-violet-50/70 via-white to-cyan-50/50 hover:border-violet-400 hover:shadow-[0_6px_18px_rgba(99,102,241,0.07)]'
                        " @click="openFilePicker" @dragover.prevent="isDragging = true"
                    @dragleave.prevent="isDragging = false" @drop.prevent="handleDrop">

                    <!-- Decorative glow -->
                    <div
                        class="pointer-events-none absolute -right-8 -top-8 h-24 w-24 rounded-full bg-cyan-200/20 blur-2xl">
                    </div>

                    <!-- Upload Icon -->
                    <div
                        class="relative flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-100 to-indigo-100 text-violet-600 shadow-sm transition-transform duration-200 group-hover:scale-105">
                        <svg class="h-5.5 w-5.5" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="1.8">
                            <path d="M12 16V4" />
                            <path d="m7 9 5-5 5 5" />
                            <path d="M5 20h14" />
                        </svg>
                    </div>


                    <!-- Dropzone Text -->
                    <div class="relative min-w-0 flex-1 max-[500px]:flex-none">

                        <h3 class="text-[12px] font-bold text-slate-900">
                            Drop your dataset here
                        </h3>

                        <p class="mt-0.5 text-[10px] leading-4 text-slate-400">
                            Drag & drop your CSV file or choose it manually.
                        </p>

                        <div class="mt-1.5 flex items-center gap-2 max-[500px]:justify-center">
                            <span
                                class="rounded-md bg-white px-1.5 py-0.5 text-[8px] font-bold text-slate-400 shadow-sm">
                                CSV
                            </span>

                            <span class="text-[9px] text-slate-400">
                                Ready for analysis
                            </span>
                        </div>

                    </div>


                    <!-- Choose Button -->
                    <button type="button"
                        class="relative shrink-0 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-3.5 py-2 text-[10px] font-bold text-white shadow-[0_5px_12px_rgba(99,102,241,0.20)] transition-all duration-200 hover:-translate-y-0.5 hover:from-violet-700 hover:to-indigo-700 hover:shadow-[0_8px_16px_rgba(99,102,241,0.25)] focus:outline-none focus:ring-2 focus:ring-violet-400 focus:ring-offset-2 max-[500px]:w-full"
                        @click.stop="openFilePicker">
                        Choose Dataset
                    </button>

                </div>


                <!-- =================================================
                     SELECTED FILE
                ================================================== -->

                <div v-if="selectedFile"
                    class="mt-3 overflow-hidden rounded-xl border border-violet-100 bg-gradient-to-r from-violet-50/80 via-white to-indigo-50/60 p-3">

                    <div class="flex items-center justify-between gap-3">

                        <div class="flex min-w-0 items-center gap-2.5">

                            <!-- File Icon -->
                            <div
                                class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-500 text-[8px] font-black uppercase text-white shadow-sm">
                                {{ fileExtension.replace(".", "") }}
                            </div>

                            <div class="min-w-0">

                                <p class="truncate text-[11px] font-bold text-slate-900" :title="selectedFile.name">
                                    {{ selectedFile.name }}
                                </p>

                                <div class="mt-0.5 flex items-center gap-2">

                                    <span class="text-[9px] text-slate-400">
                                        {{ fileSize }}
                                    </span>

                                    <span class="h-1 w-1 rounded-full bg-slate-300"></span>

                                    <span class="text-[9px] font-medium text-emerald-600">
                                        Ready
                                    </span>

                                </div>

                            </div>
                        </div>


                        <!-- Remove -->
                        <button type="button"
                            class="shrink-0 rounded-lg px-2 py-1.5 text-[9px] font-semibold text-slate-400 transition hover:bg-white hover:text-red-500"
                            @click="removeSelectedFile">
                            Remove
                        </button>

                    </div>


                    <!-- Upload Button -->
                    <button type="button" :disabled="loading"
                        class="mt-3 flex w-full items-center justify-center gap-2 rounded-lg border border-[#8b5cf6]/20 bg-gradient-to-r from-[#8b5cf6] via-[#7c3aed] to-[#6366f1] px-3 py-2.5 text-[10px] font-bold text-white shadow-[0_5px_14px_rgba(124,58,237,0.18)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_18px_rgba(124,58,237,0.25)] focus:outline-none focus:ring-2 focus:ring-[#a78bfa] focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                        @click="handleUpload">
                        <span v-if="loading"
                            class="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white"></span>

                        <svg v-else class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2">
                            <path d="M12 16V4" />
                            <path d="m7 9 5-5 5 5" />
                            <path d="M5 20h14" />
                        </svg>

                        {{
                            loading
                                ? "Uploading dataset..."
                        : "Upload & Analyze Dataset"
                        }}
                    </button>
                </div>


                <!-- =================================================
                     SUCCESS
                ================================================== -->

                <div v-if="success"
                    class="mt-3 flex items-center gap-2.5 rounded-xl border border-emerald-100 bg-gradient-to-r from-emerald-50 to-teal-50 px-3 py-2.5">

                    <div
                        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-[10px] font-bold text-emerald-600">
                        ✓
                    </div>

                    <p class="text-[10px] font-medium leading-4 text-emerald-800">
                        {{ success }}
                    </p>

                </div>


                <!-- =================================================
                     ERROR
                ================================================== -->

                <div v-if="error"
                    class="mt-3 flex items-center gap-2.5 rounded-xl border border-rose-100 bg-gradient-to-r from-rose-50 to-orange-50 px-3 py-2.5">

                    <div
                        class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-rose-100 text-[10px] font-bold text-rose-600">
                        !
                    </div>

                    <p class="text-[10px] font-medium leading-4 text-rose-800">
                        {{ error }}
                    </p>

                </div>

            </div>


            <!-- =====================================================
                 CURRENT DATASET
            ====================================================== -->

            <div v-if="hasDataset"
                class="border-t border-slate-100 bg-gradient-to-r from-slate-50 via-white to-emerald-50/40 px-3.5 py-3 sm:px-4">

                <div class="flex items-center justify-between gap-4 max-[600px]:flex-col max-[600px]:items-start">

                    <!-- Dataset Name -->
                    <div class="flex min-w-0 items-center gap-2.5">

                        <div
                            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-100 text-emerald-600">
                            <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                                stroke-width="1.8">
                                <path d="M4 5h16v14H4z" />
                                <path d="M8 9h8M8 13h6" />
                            </svg>
                        </div>

                        <div class="min-w-0">

                            <p class="text-[8px] font-bold uppercase tracking-[0.5px] text-slate-400">
                                Active Dataset
                            </p>

                            <p class="mt-0.5 truncate text-[11px] font-bold text-slate-900" :title="activeDataset.filename ||
                                activeDataset.file_name ||
                                'Uploaded dataset'
                                ">
                                {{
                                    activeDataset.filename ||
                                    activeDataset.file_name ||
                                    "Uploaded dataset"
                                }}
                            </p>

                        </div>

                    </div>


                    <!-- Dataset Stats -->
                    <div class="flex shrink-0 items-center gap-2">

                        <!-- Rows -->
                        <div class="rounded-lg border border-indigo-100 bg-indigo-50 px-2.5 py-1.5 text-center">
                            <div class="text-[11px] font-bold text-indigo-700">
                                {{ formatNumber(activeDataset.rows) }}
                            </div>

                            <div class="text-[8px] font-medium uppercase tracking-wide text-indigo-400">
                                Rows
                            </div>
                        </div>


                        <!-- Columns -->
                        <div class="rounded-lg border border-cyan-100 bg-cyan-50 px-2.5 py-1.5 text-center">
                            <div class="text-[11px] font-bold text-cyan-700">
                                {{ formatNumber(activeDataset.columns) }}
                            </div>

                            <div class="text-[8px] font-medium uppercase tracking-wide text-cyan-500">
                                Columns
                            </div>
                        </div>

                    </div>

                </div>

            </div>

        </div>

    </section>
</template>