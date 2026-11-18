<script setup>
import { computed, ref } from "vue";
import { uploadDataset, getApiErrorMessage } from "../services/api";
import Button from "./ui/Button.vue";
import Icon from "./ui/Icon.vue";
import Panel from "./ui/Panel.vue";
import StatusChip from "./ui/StatusChip.vue";

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
    <Panel title="Upload dataset" description="Add a CSV file to explore it and ask questions of it.">

        <template v-if="hasDataset" #actions>
            <StatusChip tone="success" label="Active dataset" />
        </template>

        <!-- Hidden File Input -->
        <input ref="fileInput" type="file" accept=".csv" class="hidden" @change="handleFileChange" />

        <!-- =================================================
             DROPZONE
             The whole surface accepts a click or a dropped file;
             the Choose file button is its keyboard-reachable
             control.
        ================================================== -->

        <div class="flex cursor-pointer items-center gap-4 rounded-panel border border-dashed px-5 py-6 transition-colors duration-150 ease-out-quiet max-[560px]:flex-col max-[560px]:text-center"
            :class="isDragging
                ? 'border-forest bg-forest-soft'
                : 'border-line-strong bg-canvas hover:border-forest/50'"
            @click="openFilePicker" @dragover.prevent="isDragging = true" @dragleave.prevent="isDragging = false"
            @drop.prevent="handleDrop">

            <span class="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-surface text-forest shadow-panel">
                <Icon name="upload" :size="20" />
            </span>

            <div class="min-w-0 flex-1">
                <p class="text-body font-semibold text-ink">
                    {{ isDragging ? 'Drop the file to select it' : 'Drag a CSV file here, or choose one' }}
                </p>
                <p class="mt-0.5 text-data text-ink-muted">
                    Supported format: <span class="font-mono text-caption text-ink">.csv</span>
                </p>
            </div>

            <Button variant="primary" icon="file" class="max-[560px]:w-full" @click.stop="openFilePicker">
                Choose file
            </Button>

        </div>

        <!-- =================================================
             SELECTED FILE
        ================================================== -->

        <div v-if="selectedFile" class="mt-4 rounded-panel border border-line bg-canvas p-4">

            <div class="flex items-center justify-between gap-3">

                <div class="flex min-w-0 items-center gap-3">

                    <span
                        class="grid h-9 min-w-9 shrink-0 place-items-center rounded-control bg-forest px-1.5 font-mono text-caption font-semibold text-canvas">
                        {{ fileExtension.replace(".", "") }}
                    </span>

                    <div class="min-w-0">
                        <p class="truncate text-data font-semibold text-ink" :title="selectedFile.name">
                            {{ selectedFile.name }}
                        </p>
                        <p class="mt-0.5 flex items-center gap-2 text-caption text-ink-muted">
                            <span class="tabular-nums">{{ fileSize }}</span>
                            <span class="text-forest">Ready to upload</span>
                        </p>
                    </div>

                </div>

                <Button size="sm" icon="x" @click="removeSelectedFile">
                    Remove
                </Button>

            </div>

            <Button variant="primary" icon="upload" :loading="loading" class="mt-4 w-full" @click="handleUpload">
                {{ loading ? "Uploading dataset…" : "Upload and analyze" }}
            </Button>

            <p v-if="loading" class="mt-2 text-center text-caption text-ink-muted" role="status">
                Uploading and preparing your dataset. Large files can take a while.
            </p>

        </div>

        <!-- =================================================
             SUCCESS
        ================================================== -->

        <p v-if="success" role="status"
            class="mt-4 flex items-start gap-2.5 rounded-control bg-forest-soft px-3.5 py-2.5 text-data text-forest">
            <Icon name="check" :size="16" class="mt-0.5" />
            <span>{{ success }}</span>
        </p>

        <!-- =================================================
             ERROR
        ================================================== -->

        <p v-if="error" role="alert"
            class="mt-4 flex items-start gap-2.5 rounded-control bg-danger-soft px-3.5 py-2.5 text-data text-danger">
            <Icon name="error" :size="16" class="mt-0.5" />
            <span>{{ error }}</span>
        </p>

        <!-- =====================================================
             CURRENT DATASET
        ====================================================== -->

        <template v-if="hasDataset" #footer>

            <div class="flex items-center justify-between gap-4 max-[600px]:flex-col max-[600px]:items-start">

                <div class="flex min-w-0 items-center gap-2.5">
                    <Icon name="database" :size="16" class="text-forest" />
                    <span class="shrink-0">Active:</span>
                    <span class="truncate font-medium text-ink" :title="activeDataset.filename ||
                        activeDataset.file_name ||
                        'Uploaded dataset'
                        ">
                        {{
                            activeDataset.filename ||
                            activeDataset.file_name ||
                            "Uploaded dataset"
                        }}
                    </span>
                </div>

                <dl class="flex shrink-0 items-baseline gap-5">
                    <div class="flex items-baseline gap-1.5">
                        <dt>Rows</dt>
                        <dd class="font-semibold tabular-nums text-ink">{{ formatNumber(activeDataset.rows) }}</dd>
                    </div>
                    <div class="flex items-baseline gap-1.5">
                        <dt>Columns</dt>
                        <dd class="font-semibold tabular-nums text-ink">{{ formatNumber(activeDataset.columns) }}</dd>
                    </div>
                </dl>

            </div>

        </template>

    </Panel>
</template>
