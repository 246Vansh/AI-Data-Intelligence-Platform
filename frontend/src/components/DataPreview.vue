<script setup>
import { useBreakpoints } from "@vueuse/core";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";

import { useDatasetResource } from "../composables/useDatasetResource";
import { useUiPreference } from "../composables/useUiPreference";
import {
    datasetUrls,
    getApiErrorMessage,
    getDatasetMetadata,
    getDatasetPreview,
    onCachedResponse,
} from "../services/api";
import { COLUMN_KINDS, describeColumns, kindSummary } from "../services/columnInsight";
import CellValue from "./data/CellValue.vue";
import ColumnDetails from "./data/ColumnDetails.vue";
import Button from "./ui/Button.vue";
import Dialog from "./ui/Dialog.vue";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";
import SegmentedControl from "./ui/SegmentedControl.vue";
import InspectorFrame from "./workspace/InspectorFrame.vue";

// =========================================================
// DATA WORKSPACE (Phase 3)
// =========================================================
//
// The Data tab: the preview table is the workspace, with a column
// inspector beside it (docked from 1024px, collapsible, resizable) or,
// on phones, a Rows / Columns view with a bottom sheet per column.
//
// Data sources: the preview request is this component's own. Column
// details come from the dataset's /metadata response - shared through
// api.js cachedGet() with the Schema tab and the Analyze suggestions -
// and never from /profile, whose full-row duplicate scan is the most
// expensive query the app runs and is not shown here. /metadata carries
// the same per-column figures (type, missing and distinct counts, from
// the same scan) and the row count; see services/columnInsight.js.
// Nothing is requested until the Data tab is first shown.

const PREVIEW_ROW_LIMIT = 10;
// Phone record view: fields shown per record before "Show all".
const MOBILE_FIELD_LIMIT = 6;

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
    // True while the Data workspace is the visible tab (see Dashboard).
    active: {
        type: Boolean,
        default: false,
    },
});

// ---------------------------------------------------------
// Preview + column metadata: requested on first activation
// ---------------------------------------------------------
//
// Both are requested the first time the Data tab is shown for this
// dataset (see useDatasetResource), not when the panel mounts - the
// panel is mounted, hidden, from page load. Returning to the tab reuses
// them. /metadata is the same cached request the Schema tab and the
// Analyze suggestions use, so whichever runs first is the only one sent.

const previewResource = useDatasetResource({
    datasetId: () => props.datasetId,
    active: () => props.active,
    fetch: (id, options) => getDatasetPreview(id, options),
    errorMessage: (err) => getApiErrorMessage(err) || "Unable to load the dataset preview.",
});

// A failure here only means fewer details in the column inspector; the
// Schema tab reports metadata errors itself.
const metadataResource = useDatasetResource({
    datasetId: () => props.datasetId,
    active: () => props.active,
    fetch: (id, options) => getDatasetMetadata(id, options),
});

const dataset = previewResource.data;
const error = previewResource.error;
const refreshing = previewResource.refreshing;
// Also true before the first activation's request starts, so the
// panel never renders an empty table for a dataset that has rows.
const loading = computed(() =>
    Boolean(props.datasetId) && (previewResource.loading.value || !previewResource.settled.value),
);
const searchQuery = ref("");

// Follows a newer /metadata response stored elsewhere (the Schema tab's
// Refresh). No request is sent from here.
const metadataOverride = ref(null);
const metadata = computed(() => metadataOverride.value ?? metadataResource.data.value);

const stopFollowingRefreshes = onCachedResponse((url, data) => {
    if (props.datasetId && url === datasetUrls.metadata(props.datasetId)) {
        metadataOverride.value = data;
    }
});

onBeforeUnmount(stopFollowingRefreshes);

// Refresh reloads the preview rows from the server (bypassing the
// browser cache; the preview is a fresh query every time). Column
// details are left as they are - a dataset never changes after upload -
// unless they failed to load, in which case they are requested again.
function refresh() {
    previewResource.refresh();
    if (metadataResource.error.value) {
        metadataResource.load();
    }
}

// ---------------------------------------------------------
// Rows and columns
// ---------------------------------------------------------

const sourceRows = computed(() =>
    Array.isArray(dataset.value?.rows)
        ? dataset.value.rows
        : [],
);

const previewColumns = computed(() =>
    Array.isArray(dataset.value?.columns)
        ? dataset.value.columns
        : [],
);

// Search filters the preview sample only (as before). Each entry keeps
// its position in the preview, so row numbers stay stable while
// filtering.
const filteredRows = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();

    return sourceRows.value
        .slice(0, PREVIEW_ROW_LIMIT)
        .map((row, index) => ({ row: row || {}, number: index + 1 }))
        .filter(({ row }) =>
            !query ||
            Object.values(row).some((value) =>
                String(value ?? "")
                    .toLowerCase()
                    .includes(query),
            ),
        );
});

const totalRowCount = computed(() => Math.min(sourceRows.value.length, PREVIEW_ROW_LIMIT));

// The whole dataset's row count, from the /metadata this panel already
// loads (no extra request); null when unknown.
const datasetRowCount = computed(() => {
    const rows = Number(metadata.value?.row_count);
    return Number.isFinite(rows) && rows > 0 ? rows.toLocaleString() : null;
});
const visibleRowCount = computed(() => filteredRows.value.length);
const isSearchActive = computed(() => Boolean(searchQuery.value.trim()));

const columns = computed(() =>
    describeColumns({
        columns: previewColumns.value,
        rows: sourceRows.value.slice(0, PREVIEW_ROW_LIMIT),
        metadata: metadata.value,
    }),
);

const typeSummary = computed(() => kindSummary(columns.value));

// Only when the column metadata is available: how many columns have any
// missing value across the whole dataset (a count of columns, taken
// from the backend's own missing counts).
const columnsWithMissing = computed(() => {
    if (!metadata.value) return null;
    const known = columns.value.filter((column) => column.missingCount !== null);
    return known.length ? known.filter((column) => column.missingCount > 0).length : null;
});

function clearSearch() {
    searchQuery.value = "";
}

// Column widths: by kind, widened for long names (capped - the full
// name is in the header's tooltip and in the inspector).
const KIND_WIDTH = { number: 120, date: 184, boolean: 96, text: 200, other: 140 };

const ROW_NUMBER_WIDTH = 48;

function columnWidth(column) {
    const byName = Math.min(280, Math.ceil(column.name.length * 7.4) + 56);
    return Math.max(KIND_WIDTH[column.kind] || 140, byName);
}

// The table gets the exact sum as its width: with `table-layout: fixed`
// and a content-sized (max-content) width, browsers widen columns past
// their <col> widths to fit long values. (min-width: 100% still fills
// the workspace when there are few columns.)
const tableWidth = computed(() => ROW_NUMBER_WIDTH + columns.value.reduce((sum, column) => sum + columnWidth(column), 0));

const kindOf = (kind) => COLUMN_KINDS[kind] || COLUMN_KINDS.other;

function formatPercent(value) {
    if (value === null) return "";
    return value > 0 && value < 0.1 ? "<0.1%" : `${Number(value.toFixed(1))}%`;
}

// ---------------------------------------------------------
// Layout + column selection
// ---------------------------------------------------------

const breakpoints = useBreakpoints({ tablet: 768, desktop: 1024, wide: 1440 });
const isMobile = breakpoints.smaller("tablet");
const inspectorDocked = breakpoints.greaterOrEqual("desktop");

// First visit: open on wide screens, collapsed on laptops (the table
// gets the width; selecting a column opens it). Then the user's choice.
const inspectorOpen = useUiPreference(
    "data.inspector-open",
    typeof window === "undefined" ? true : window.innerWidth >= 1440,
);

const selectedName = ref(null);
const selectedColumn = computed(() => columns.value.find((column) => column.name === selectedName.value) || null);
const sheetOpen = ref(false);
const tableScroller = ref(null);

// Desktop details card: the picked column, else the first numeric one
// (as in the visual reference), so the card is never blank. Display
// only - it does not mark a selection or open anything.
const detailsColumn = computed(
    () => selectedColumn.value || columns.value.find((column) => column.kind === "number") || columns.value[0] || null,
);

// A new preview (refresh / other dataset) drops a selection that no
// longer exists.
watch(previewColumns, (names) => {
    if (selectedName.value && !names.includes(selectedName.value)) {
        selectedName.value = null;
        sheetOpen.value = false;
    }
});

function selectColumn(name, { reveal = false } = {}) {
    selectedName.value = name;

    if (isMobile.value) {
        sheetOpen.value = true;
        return;
    }

    if (inspectorDocked.value) {
        inspectorOpen.value = true;
    }

    // Picked from the inspector list: bring the column into view.
    if (reveal) {
        nextTick(() => {
            const header = [...(tableScroller.value?.querySelectorAll("th[data-column]") || [])]
                .find((th) => th.dataset.column === name);
            header?.scrollIntoView({ block: "nearest", inline: "nearest" });
        });
    }
}

// Phone: Rows / Columns
const mobileView = ref("rows");
const MOBILE_VIEWS = [
    { value: "rows", label: "Rows", icon: "rows" },
    { value: "columns", label: "Columns", icon: "columns" },
];

const expandedRecords = ref(new Set());

function toggleRecord(number) {
    const next = new Set(expandedRecords.value);
    next.has(number) ? next.delete(number) : next.add(number);
    expandedRecords.value = next;
}

function recordFields(number) {
    return expandedRecords.value.has(number) ? columns.value : columns.value.slice(0, MOBILE_FIELD_LIMIT);
}
</script>

<template>
    <section class="flex min-h-0 flex-col" :class="isMobile ? '' : 'h-full'" aria-label="Data preview">

        <!-- =====================================================
             TABLET / DESKTOP: table canvas + column inspector
        ====================================================== -->

        <InspectorFrame v-if="!isMobile" storage-key="workspace-data-inspector-v2" inspector-label="Columns"
            :stacked="!inspectorDocked" :collapsed="!inspectorOpen" bare :default-size="300">

            <div class="flex flex-col gap-5 px-4 pb-6 pt-5 sm:px-6 lg:pl-9 lg:pr-5 lg:pt-7" :class="inspectorDocked ? 'h-full' : ''">

                <!-- Header: title + tools (size, memory and quality are in
                     the top bar above). -->
                <header class="flex shrink-0 flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 class="text-[28px] font-bold leading-tight tracking-[-0.02em] text-ink">Data Explorer</h2>
                        <p class="mt-1 text-body text-ink-muted">Preview your dataset and inspect column details.</p>
                    </div>
                    <div class="flex flex-wrap items-center gap-2">
                        <div v-if="dataset" class="relative w-[260px] max-md:w-full">
                            <Icon name="search" :size="16"
                                class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted" />
                            <input v-model="searchQuery" type="search" placeholder="Search in preview…"
                                aria-label="Search the preview rows"
                                class="h-10 w-full appearance-none rounded-[10px] border border-[#e6decd] bg-surface pl-10 pr-9 text-data text-ink transition-colors duration-150 placeholder:text-ink-muted focus-visible:border-forest [&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden" />
                            <button v-if="searchQuery" type="button" aria-label="Clear search"
                                class="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-control text-ink-muted hover:bg-sunken hover:text-ink"
                                @click="clearSearch">
                                <Icon name="x" :size="14" />
                            </button>
                        </div>
                        <Button v-if="dataset" icon="refresh" :loading="refreshing" class="h-10 rounded-[10px] bg-surface px-4"
                            title="Reload the preview rows from the server"
                            @click="refresh">
                            Refresh
                        </Button>
                        <Button v-if="dataset && inspectorDocked && !inspectorOpen" icon="panel-right"
                            class="h-10 rounded-[10px] bg-surface px-4" :aria-pressed="false" @click="inspectorOpen = true">
                            Column details
                        </Button>
                    </div>
                </header>

                <div class="flex min-h-0 shrink flex-col overflow-hidden rounded-[16px] border border-[#e6decd] bg-surface shadow-panel">

                <!-- LOADING -->
                <div v-if="loading" aria-busy="true" aria-label="Loading preview rows" class="min-h-0 flex-1">
                    <div class="h-10 border-b border-line bg-sunken"></div>
                    <div v-for="row in 8" :key="row" class="flex gap-6 border-b border-line px-6 py-3">
                        <div v-for="column in 6" :key="column" class="h-3 flex-1 animate-pulse rounded-control bg-sunken"></div>
                    </div>
                </div>

                <!-- ERROR -->
                <div v-else-if="error" class="p-4 sm:p-6">
                    <div role="alert" class="flex items-start gap-3 rounded-control bg-danger-soft px-4 py-3">
                        <Icon name="error" :size="16" class="mt-0.5 text-danger" />
                        <div class="min-w-0 flex-1">
                            <p class="text-data font-semibold text-danger">Unable to load preview</p>
                            <p class="mt-0.5 break-words text-data text-ink">{{ error }}</p>
                        </div>
                        <Button size="sm" icon="refresh" @click="previewResource.load()">Retry</Button>
                    </div>
                </div>

                <!-- NO DATASET -->
                <div v-else-if="!dataset" class="p-4 sm:p-6">
                    <EmptyState icon="table" title="No dataset selected"
                        description="Upload or select a dataset to preview its records." />
                </div>

                <!-- EMPTY DATASET -->
                <EmptyState v-else-if="!sourceRows.length" icon="table" title="No records available"
                    description="The uploaded dataset does not contain preview records." />

                <!-- NO SEARCH RESULTS -->
                <EmptyState v-else-if="!filteredRows.length" icon="search" title="No matching preview rows"
                    :description="`Nothing in the preview matches “${searchQuery}”.`">
                    <template #action>
                        <Button size="sm" @click="clearSearch">Clear search</Button>
                    </template>
                </EmptyState>

                <!-- TABLE -->
                <template v-else>

                    <div ref="tableScroller"
                        class="min-h-0 overflow-auto overscroll-contain [scrollbar-color:var(--color-line-strong)_transparent] [scrollbar-width:thin]"
                        :class="inspectorDocked ? 'flex-1' : 'max-h-[560px]'">

                        <table class="min-w-full border-separate border-spacing-0 text-left"
                            :style="{ tableLayout: 'fixed', width: `${tableWidth}px` }">

                            <colgroup>
                                <col :style="{ width: `${ROW_NUMBER_WIDTH}px` }" />
                                <col v-for="column in columns" :key="`width-${column.name}`"
                                    :style="{ width: `${columnWidth(column)}px` }" />
                            </colgroup>

                            <thead class="sticky top-0 z-10">
                                <tr>
                                    <th scope="col"
                                        class="sticky left-0 z-20 border-b border-[#ece5d6] bg-[#f6f1e5] px-2 text-center text-data font-semibold text-ink">
                                        #
                                    </th>
                                    <th v-for="column in columns" :key="column.name" scope="col" :data-column="column.name"
                                        class="border-b border-line p-0 align-bottom transition-colors duration-150"
                                        :class="column.name === selectedName ? 'bg-forest-soft shadow-[inset_0_-2px_0_var(--color-forest)]' : 'bg-[#f6f1e5]'">
                                        <button type="button" :aria-pressed="column.name === selectedName"
                                            :title="column.name"
                                            class="flex w-full flex-col gap-0.5 px-3 py-2.5 text-left outline-none transition-colors duration-150 hover:bg-forest-soft/70 focus-visible:bg-forest-soft focus-visible:shadow-[inset_0_0_0_2px_var(--color-forest)]"
                                            :class="column.kind === 'number' ? 'items-end text-right' : ''"
                                            @click="selectColumn(column.name)">
                                            <span class="flex max-w-full items-center gap-1.5"
                                                :class="column.kind === 'number' ? 'flex-row-reverse' : ''">
                                                <span class="truncate text-data font-semibold text-ink">{{ column.name }}</span>
                                            </span>
                                            <span class="max-w-full truncate text-caption text-ink-muted">
                                                {{ column.dataType || kindOf(column.kind).label.toLowerCase() }}<template
                                                    v-if="column.missingCount"> · <span class="text-warn-ink">{{ formatPercent(column.missingPercentage) || column.missingCount }} missing</span></template>
                                            </span>
                                        </button>
                                    </th>
                                </tr>
                            </thead>

                            <tbody class="text-data">
                                <tr v-for="{ row, number } in filteredRows" :key="number" class="group">
                                    <td
                                        class="sticky left-0 z-[5] border-b border-[#efe8da] bg-surface px-2 py-2.5 text-center align-top text-data tabular-nums text-ink group-hover:bg-canvas">
                                        {{ number }}
                                    </td>
                                    <td v-for="column in columns" :key="column.name"
                                        class="border-b border-[#efe8da] px-3 py-2.5 align-top text-ink group-hover:bg-canvas"
                                        :class="[
                                            column.kind === 'number' ? 'text-right tabular-nums' : '',
                                            column.kind === 'date' ? 'tabular-nums' : '',
                                            column.name === selectedName ? 'bg-forest-soft/45' : 'bg-surface',
                                        ]">
                                        <div class="overflow-hidden text-ellipsis whitespace-nowrap">
                                            <CellValue :value="row[column.name]" :kind="column.kind" />
                                        </div>
                                    </td>
                                </tr>
                            </tbody>

                        </table>
                    </div>

                    <p
                        class="flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 border-t border-[#ece5d6] bg-[#f8f4ea] px-5 py-2.5 text-data text-ink-muted">
                        <span>
                            <template v-if="isSearchActive">
                                <span class="font-semibold tabular-nums text-ink">{{ visibleRowCount }}</span> matching ·
                            </template>
                            Showing first <span class="tabular-nums">{{ totalRowCount }}</span> rows<template
                                v-if="datasetRowCount"> of <span class="tabular-nums">{{ datasetRowCount }}</span></template>
                        </span>
                        <ul v-if="typeSummary.length" class="flex items-center gap-3 text-caption" aria-label="Column types">
                            <li v-for="entry in typeSummary" :key="entry.kind" class="flex items-center gap-1"
                                :title="`${entry.count} ${entry.label.toLowerCase()} column${entry.count === 1 ? '' : 's'}`">
                                <Icon :name="entry.icon" :size="14" class="text-forest" />
                                <span class="tabular-nums text-ink">{{ entry.count }}</span>
                                <span class="sr-only">{{ entry.label }} columns</span>
                            </li>
                        </ul>
                        <span v-if="columnsWithMissing !== null" class="flex items-center gap-1.5 text-caption">
                            <span aria-hidden="true" class="h-1.5 w-1.5 rounded-full"
                                :class="columnsWithMissing ? 'bg-gold' : 'bg-sage'"></span>
                            <template v-if="columnsWithMissing">
                                <span class="tabular-nums text-ink">{{ columnsWithMissing }}</span>
                                column{{ columnsWithMissing === 1 ? "" : "s" }} with missing values
                            </template>
                            <template v-else>No missing values</template>
                        </span>
                        <span class="flex items-center gap-3 text-caption">
                            <span><span class="font-mono italic text-ink-muted/70">null</span> missing value</span>
                            <span><span class="font-mono italic text-ink-muted/70">empty</span> blank text</span>
                        </span>
                        <span class="ml-auto text-caption max-md:ml-0">Select a column header to inspect it.</span>
                    </p>

                </template>

                </div>

            </div>

            <!-- ===================================================
                 COLUMN INSPECTOR
            ==================================================== -->

            <template v-if="dataset && !loading && !error && columns.length" #inspector>
              <!-- Cards on the canvas: details, then every column. -->
              <div class="flex flex-col gap-4 pb-6 pl-1 pr-6" :class="inspectorDocked ? 'h-full pt-[112px]' : 'px-4 pt-2'">

                <section aria-labelledby="column-details-title"
                    class="shrink-0 rounded-[16px] border border-[#e6decd] bg-surface px-4 pb-4 pt-3.5 shadow-panel" aria-live="polite">
                    <div class="mb-3 flex items-center justify-between gap-2">
                        <h3 id="column-details-title" class="text-lead font-semibold text-ink">Column Details</h3>
                        <button v-if="inspectorDocked" type="button" aria-label="Hide column details"
                            class="grid h-8 w-8 place-items-center rounded-control text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
                            @click="inspectorOpen = false">
                            <Icon name="panel-right" :size="16" />
                        </button>
                    </div>
                    <ColumnDetails v-if="detailsColumn" :column="detailsColumn" />
                    <p v-else class="text-data text-ink-muted">
                        Select a column to see its type, role, missing values and unique count.
                    </p>
                </section>

                <section aria-labelledby="all-columns-title"
                    class="flex min-h-0 shrink flex-col rounded-[16px] border border-[#e6decd] bg-surface pb-2 pt-3.5 shadow-panel">
                    <h3 id="all-columns-title" class="px-4 pb-2 text-data font-semibold text-ink">
                        All columns <span class="font-normal tabular-nums text-ink-muted">{{ columns.length }}</span>
                    </h3>
                    <ul class="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]" aria-label="All columns">
                        <li v-for="column in columns" :key="column.name">
                            <button type="button" :aria-pressed="column.name === selectedName"
                                class="flex w-full items-center gap-2 px-4 py-1.5 text-left transition-colors duration-150 hover:bg-sunken/60"
                                :class="column.name === selectedName ? 'bg-forest-soft' : ''"
                                @click="selectColumn(column.name, { reveal: true })">
                                <Icon :name="kindOf(column.kind).icon" :size="14" class="shrink-0 text-ink-muted" />
                                <span class="min-w-0 flex-1 truncate text-data text-ink" :title="column.name">{{ column.name }}</span>
                                <span v-if="column.missingCount" class="shrink-0 text-caption tabular-nums text-warn-ink">
                                    {{ formatPercent(column.missingPercentage) || column.missingCount }}
                                </span>
                            </button>
                        </li>
                    </ul>
                </section>
              </div>

            </template>

        </InspectorFrame>

        <!-- =====================================================
             PHONE: Rows / Columns, column details in a sheet
        ====================================================== -->

        <div v-else class="flex flex-col gap-3 px-4 py-4">

            <div class="flex items-center justify-between gap-3">
                <p class="text-data text-ink">
                    <span class="font-semibold">Preview</span>
                    <span class="text-ink-muted"> · first {{ PREVIEW_ROW_LIMIT }} rows</span>
                </p>
                <Button v-if="dataset" size="sm" icon="refresh" :loading="refreshing" aria-label="Refresh preview"
                    title="Reload the preview rows from the server"
                    @click="refresh">
                    <span class="sr-only">Refresh</span>
                </Button>
            </div>

            <div v-if="dataset && !loading && !error" class="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-muted">
                <span v-for="entry in typeSummary" :key="entry.kind" class="flex items-center gap-1">
                    <Icon :name="entry.icon" :size="14" class="text-forest" />
                    <span class="tabular-nums text-ink">{{ entry.count }}</span> {{ entry.label.toLowerCase() }}
                </span>
                <span v-if="columnsWithMissing" class="flex items-center gap-1.5">
                    <span aria-hidden="true" class="h-1.5 w-1.5 rounded-full bg-gold"></span>
                    {{ columnsWithMissing }} with missing values
                </span>
            </div>

            <SegmentedControl v-if="dataset && !loading && !error && sourceRows.length" v-model="mobileView"
                :items="MOBILE_VIEWS" label="Preview view" class="self-start" />

            <!-- States (same as desktop) -->
            <div v-if="loading" aria-busy="true" aria-label="Loading preview rows" class="space-y-3">
                <div v-for="row in 4" :key="row" class="h-16 animate-pulse rounded-control bg-sunken"></div>
            </div>

            <div v-else-if="error" role="alert" class="flex flex-col items-start gap-2 rounded-control bg-danger-soft px-4 py-3">
                <p class="text-data font-semibold text-danger">Unable to load preview</p>
                <p class="break-words text-data text-ink">{{ error }}</p>
                <Button size="sm" icon="refresh" @click="previewResource.load()">Retry</Button>
            </div>

            <EmptyState v-else-if="!dataset" icon="table" title="No dataset selected"
                description="Upload or select a dataset to preview its records." />

            <EmptyState v-else-if="!sourceRows.length" icon="table" title="No records available"
                description="The uploaded dataset does not contain preview records." />

            <!-- ROWS: each preview record as a field list -->
            <template v-else-if="mobileView === 'rows'">

                <div class="relative">
                    <Icon name="search" :size="16"
                        class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                    <input v-model="searchQuery" type="search" placeholder="Search preview rows"
                        aria-label="Search the preview rows"
                        class="h-11 w-full appearance-none rounded-control border border-line-strong bg-surface pl-9 pr-11 text-body text-ink placeholder:text-ink-muted focus-visible:border-forest [&::-webkit-search-cancel-button]:hidden" />
                    <button v-if="searchQuery" type="button" aria-label="Clear search"
                        class="absolute right-0.5 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-control text-ink-muted"
                        @click="clearSearch">
                        <Icon name="x" :size="16" />
                    </button>
                </div>

                <EmptyState v-if="!filteredRows.length" icon="search" title="No matching preview rows"
                    :description="`Nothing in the preview matches “${searchQuery}”.`">
                    <template #action>
                        <Button size="sm" @click="clearSearch">Clear search</Button>
                    </template>
                </EmptyState>

                <ol v-else class="divide-y divide-line border-y border-line" aria-label="Preview rows">
                    <li v-for="{ row, number } in filteredRows" :key="number" class="py-3">
                        <p class="mb-1.5 font-mono text-caption text-ink-muted">Row {{ number }}</p>
                        <dl class="space-y-1">
                            <div v-for="column in recordFields(number)" :key="column.name"
                                class="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] items-baseline gap-3">
                                <dt class="truncate font-mono text-caption text-ink-muted" :title="column.name">{{ column.name }}</dt>
                                <dd class="min-w-0 break-words text-data text-ink"
                                    :class="column.kind === 'number' ? 'text-right tabular-nums' : ''">
                                    <CellValue :value="row[column.name]" :kind="column.kind" />
                                </dd>
                            </div>
                        </dl>
                        <button v-if="columns.length > MOBILE_FIELD_LIMIT" type="button"
                            class="mt-1.5 min-h-11 text-caption font-medium text-forest" :aria-expanded="expandedRecords.has(number)"
                            @click="toggleRecord(number)">
                            {{ expandedRecords.has(number) ? "Show fewer fields" : `Show all ${columns.length} fields` }}
                        </button>
                    </li>
                </ol>

                <p class="text-caption text-ink-muted">
                    <template v-if="isSearchActive"><span class="tabular-nums">{{ visibleRowCount }}</span> of </template>
                    <span class="tabular-nums">{{ totalRowCount }}</span> preview rows.
                    <span class="font-mono italic text-ink-muted/70">null</span> = missing,
                    <span class="font-mono italic text-ink-muted/70">empty</span> = blank text.
                </p>

            </template>

            <!-- COLUMNS: tap for details -->
            <ul v-else class="divide-y divide-line border-y border-line" aria-label="All columns">
                <li v-for="column in columns" :key="column.name">
                    <button type="button" class="flex min-h-12 w-full items-center gap-3 py-2 text-left"
                        aria-haspopup="dialog" @click="selectColumn(column.name)">
                        <Icon :name="kindOf(column.kind).icon" :size="16" class="shrink-0 text-forest" />
                        <span class="min-w-0 flex-1">
                            <span class="block truncate font-mono text-data text-ink">{{ column.name }}</span>
                            <span class="block text-caption text-ink-muted">
                                {{ column.dataType || kindOf(column.kind).label.toLowerCase() }}<template
                                    v-if="column.missingCount"> · <span class="text-warn-ink">{{ formatPercent(column.missingPercentage) || column.missingCount }} missing</span></template>
                            </span>
                        </span>
                        <Icon name="chevron-right" :size="16" class="shrink-0 text-ink-muted" />
                    </button>
                </li>
            </ul>

            <Dialog v-model:open="sheetOpen" side="bottom" hide-title
                :title="selectedColumn ? `Column ${selectedColumn.name}` : 'Column'"
                :description="selectedColumn ? kindOf(selectedColumn.kind).label : ''">
                <ColumnDetails v-if="selectedColumn" :column="selectedColumn" />
            </Dialog>

        </div>

    </section>
</template>
