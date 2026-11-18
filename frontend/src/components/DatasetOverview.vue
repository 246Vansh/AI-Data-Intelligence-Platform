<script setup>
import { computed, onMounted, ref } from "vue";
import { getDatasetProfile, getApiErrorMessage } from "../services/api";
import Button from "./ui/Button.vue";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";
import Panel from "./ui/Panel.vue";
import StatusChip from "./ui/StatusChip.vue";

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
});

const profile = ref(null);
const loading = ref(true);
const refreshing = ref(false);
const error = ref(null);

async function loadProfile(options = {}) {
    const isRefresh = options.refresh === true;

    // Captured so a response that resolves after the user has
    // already switched datasets can be detected and ignored below.
    const requestedDatasetId = props.datasetId;

    // No dataset selected (e.g. right after a page refresh, before
    // any dataset is re-selected) - show the empty state instead of
    // falling back to the legacy no-id endpoint, which would return
    // whatever dataset the backend still has active in memory and
    // disagree with the sidebar/header, which already show "no
    // dataset loaded" in that case.
    if (!requestedDatasetId) {
        profile.value = null;
        error.value = null;
        loading.value = false;
        refreshing.value = false;
        return;
    }

    try {
        if (isRefresh) {
            refreshing.value = true;
        } else {
            loading.value = true;
        }

        error.value = null;

        const response = await getDatasetProfile(requestedDatasetId, { force: isRefresh });

        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        profile.value = response;
    } catch (err) {
        if (requestedDatasetId !== props.datasetId) {
            return;
        }

        console.error("Dataset profile error:", err);

        profile.value = null;

        error.value =
            getApiErrorMessage(err) ||
            "Unable to load dataset statistics.";
    } finally {
        if (requestedDatasetId === props.datasetId) {
            loading.value = false;
            refreshing.value = false;
        }
    }
}

const hasProfile = computed(() => Boolean(profile.value));

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

const memoryUsage = computed(() => {
    const bytes = Number(profile.value?.memory_usage_bytes);

    if (!Number.isFinite(bytes) || bytes < 0) {
        return "0.00";
    }

    return (bytes / 1024 / 1024).toFixed(2);
});

const duplicatePercentage = computed(() => {
    const rows = Number(profile.value?.rows);
    const duplicates = Number(profile.value?.duplicate_rows);

    if (
        !Number.isFinite(rows) ||
        !Number.isFinite(duplicates) ||
        rows <= 0
    ) {
        return null;
    }

    return Math.min(
        Math.max((duplicates / rows) * 100, 0),
        100,
    ).toFixed(1);
});

const duplicateStatus = computed(() => {
    const percentage = Number(duplicatePercentage.value);

    if (!Number.isFinite(percentage) || percentage === 0) {
        return {
            label: "Clean",
            classes: "bg-emerald-50 text-emerald-700",
        };
    }

    if (percentage <= 5) {
        return {
            label: "Low",
            classes: "bg-amber-50 text-amber-700",
        };
    }

    return {
        label: "Review",
        classes: "bg-rose-50 text-rose-700",
    };
});

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return value ?? "—";
    }

    return new Intl.NumberFormat("en-US").format(number);
}

onMounted(() => {
    loadProfile();
});
</script>

<template>
    <Panel title="Overview" description="Size and shape of the selected dataset.">

        <template v-if="hasProfile && !loading" #actions>
            <StatusChip tone="success" label="Ready" />
            <Button size="sm" icon="refresh" :loading="refreshing" @click="loadProfile({ refresh: true })">
                {{ refreshing ? "Refreshing…" : "Refresh" }}
            </Button>
        </template>

        <!-- =========================================================
             LOADING
        ========================================================== -->

        <div v-if="loading" class="grid grid-cols-2 gap-px overflow-clip rounded-panel bg-line xl:grid-cols-4"
            aria-busy="true" aria-label="Loading dataset statistics">
            <div v-for="index in 4" :key="index" class="bg-surface px-5 py-4">
                <div class="h-3 w-16 animate-pulse rounded-control bg-sunken"></div>
                <div class="mt-3 h-6 w-24 animate-pulse rounded-control bg-sunken"></div>
                <div class="mt-2 h-3 w-20 animate-pulse rounded-control bg-sunken"></div>
            </div>
        </div>

        <!-- =========================================================
             ERROR
        ========================================================== -->

        <div v-else-if="error" role="alert"
            class="flex items-start gap-3 rounded-control bg-danger-soft px-4 py-3 max-[600px]:flex-col">

            <Icon name="error" :size="16" class="mt-0.5 text-danger" />

            <div class="min-w-0 flex-1">
                <p class="text-data font-semibold text-danger">
                    Unable to load dataset overview
                </p>
                <p class="mt-0.5 text-data text-ink">
                    {{ error }}
                </p>
            </div>

            <Button size="sm" icon="refresh" @click="loadProfile()">
                Retry
            </Button>

        </div>

        <!-- =========================================================
             STATISTICS
             One ruled strip rather than four separate cards: the
             1px gaps on a `line` background draw the separators.
        ========================================================== -->

        <dl v-else-if="profile" class="grid grid-cols-2 gap-px overflow-clip rounded-panel bg-line xl:grid-cols-4">

            <!-- ROWS -->
            <div class="bg-surface px-5 py-4">
                <dt class="flex items-center gap-1.5 text-caption text-ink-muted">
                    <Icon name="rows" :size="14" />
                    Rows
                </dt>
                <dd class="mt-1.5 truncate text-title font-semibold tabular-nums text-ink">
                    {{ rowCount }}
                </dd>
                <dd class="mt-0.5 text-caption text-ink-muted">
                    Total records
                </dd>
            </div>

            <!-- COLUMNS -->
            <div class="bg-surface px-5 py-4">
                <dt class="flex items-center gap-1.5 text-caption text-ink-muted">
                    <Icon name="columns" :size="14" />
                    Columns
                </dt>
                <dd class="mt-1.5 truncate text-title font-semibold tabular-nums text-ink">
                    {{ columnCount }}
                </dd>
                <dd class="mt-0.5 text-caption text-ink-muted">
                    Total fields
                </dd>
            </div>

            <!-- DUPLICATES -->
            <div class="bg-surface px-5 py-4">
                <dt class="flex items-center gap-1.5 text-caption text-ink-muted">
                    <Icon name="copy" :size="14" />
                    Duplicate rows
                </dt>
                <dd class="mt-1.5 flex flex-wrap items-center gap-2">
                    <span class="truncate text-title font-semibold tabular-nums text-ink">{{ duplicateRows }}</span>
                    <StatusChip v-if="duplicatePercentage !== null"
                        :tone="{ Clean: 'success', Low: 'warning', Review: 'error' }[duplicateStatus.label] || 'neutral'"
                        :label="duplicateStatus.label" />
                </dd>
                <dd class="mt-0.5 text-caption tabular-nums text-ink-muted">
                    {{ duplicatePercentage !== null ? `${duplicatePercentage}% of records` : "Duplicate rows" }}
                </dd>
            </div>

            <!-- MEMORY -->
            <div class="bg-surface px-5 py-4">
                <dt class="flex items-center gap-1.5 text-caption text-ink-muted">
                    <Icon name="cpu" :size="14" />
                    Memory
                </dt>
                <dd class="mt-1.5 flex items-baseline gap-1 truncate text-title font-semibold tabular-nums text-ink">
                    {{ memoryUsage }}
                    <span class="text-data font-medium text-ink-muted">MB</span>
                </dd>
                <dd class="mt-0.5 text-caption text-ink-muted">
                    In memory
                </dd>
            </div>

        </dl>

        <!-- =========================================================
             NO DATASET SELECTED
        ========================================================== -->

        <EmptyState v-else icon="overview" title="No dataset selected"
            description="Upload or select a dataset to see its overview." />

    </Panel>
</template>
