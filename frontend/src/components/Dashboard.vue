<script setup>
import { computed, ref, nextTick, watch, onMounted, onBeforeUnmount } from "vue";
import { useBreakpoints } from "@vueuse/core";

import AnalyticsBuilder from "./AnalyticsBuilder.vue";
import DataPreview from "./DataPreview.vue";
import DatasetUpload from "./DatasetUpload.vue";
import DatasetMetadata from "./DatasetMetadata.vue";
import DataQuality from "./DataQuality.vue";
import Button from "./ui/Button.vue";
import Dialog from "./ui/Dialog.vue";
import EmptyState from "./ui/EmptyState.vue";
import TabNav from "./ui/TabNav.vue";
import TabPanel from "./ui/TabPanel.vue";
import Tabs from "./ui/Tabs.vue";
import AccountMenu from "./workspace/AccountMenu.vue";
import AppSidebar from "./workspace/AppSidebar.vue";
import BrandMark from "./workspace/BrandMark.vue";
import ContextBar from "./workspace/ContextBar.vue";
import DatasetLibrary from "./workspace/DatasetLibrary.vue";
import Icon from "./ui/Icon.vue";

import { useWorkspaceTab } from "../composables/useWorkspaceTab";
import { pickInitialDatasetId } from "../services/datasetSelection";
import { initials } from "../services/userDisplay";

import {
    useAnalysisContext,
    ANALYSIS_MODES,
    ANALYSIS_MODE_LABELS,
} from "../composables/useAnalysisContext";

import {
    listDatasets,
    deleteDataset,
    getApiErrorMessage,
    onDatasetMissing,
    evictDatasetCache,
} from "../services/api";

// =========================================================
// PROPS
// =========================================================

const props = defineProps({
    incomingQuestion: {
        type: String,
        default: "",
    },
    // Signed-in user's public profile ({id, email}); null hides the
    // account controls.
    user: {
        type: Object,
        default: null,
    },
    signingOut: {
        type: Boolean,
        default: false,
    },
});

const emit = defineEmits(["logout"]);

const userInitials = computed(() => initials(props.user));

// All sections share one scroll container: a newly shown section starts
// at its top instead of at the previous section's scroll offset.
const sectionScroller = ref(null);

// =========================================================
// WORKSPACE SHELL STATE (presentation only)
// =========================================================
//
// Workspace Phase 1. None of this touches dataset, analysis or auth
// state - it only decides which tab is visible and where the dataset
// library and dialogs are shown.
//
// Breakpoints (visual redesign, Stage 1): >= 1024 the forest sidebar is
// docked and holds the section navigation, the dataset library and the
// account; < 1024 the compact shell takes over - an ivory top bar, a
// forest navigation drawer (library + account) and a bottom section bar.

const WORKSPACE_TAB_ITEMS = [
    { value: "analyze", label: "Analyze", icon: "sparkle" },
    { value: "data", label: "Data", icon: "table" },
    { value: "schema", label: "Schema", icon: "columns" },
    { value: "quality", label: "Quality", icon: "shield-check" },
];

const uploadOpen = ref(false);
// Mobile navigation drawer (library + account).
const libraryOverlayOpen = ref(false);

const {
    tab: workspaceTab,
    setTab: setWorkspaceTab,
    initialUploadRequested,
} = useWorkspaceTab({
    onUploadRequested: () => {
        uploadOpen.value = true;
    },
});

if (initialUploadRequested) {
    uploadOpen.value = true;
}

const breakpoints = useBreakpoints({ desktop: 1024 });
// "Mobile" = the compact shell (phones and narrow tablets).
const isMobile = breakpoints.smaller("desktop");

function openLibrary() {
    if (!isMobile.value) {
        return; // docked in the sidebar
    }
    libraryOverlayOpen.value = true;
}

watch(workspaceTab, () => {
    if (sectionScroller.value) {
        sectionScroller.value.scrollTop = 0;
    }
});

// The drawer only exists in the compact shell.
watch(isMobile, (mobile) => {
    if (!mobile) {
        libraryOverlayOpen.value = false;
    }
});

function chooseDataset(datasetId) {
    selectDataset(datasetId);
    libraryOverlayOpen.value = false;
}

function openUpload() {
    libraryOverlayOpen.value = false;
    uploadOpen.value = true;
}

// =========================================================
// STATE
// =========================================================

const refreshKey = ref(0);
const selectedQuestion = ref("");
const question = ref("");
const activeSection = ref("overview");

const error = ref(null);
const result = ref(null);

// =========================================================
// DATASET STATE (central multi-dataset state)
// =========================================================
//
// `datasets` holds every dataset uploaded this session (each one
// keeps living in the backend registry by its own dataset_id, so
// switching back and forth never loses data).

const datasets = ref([]);

const deletingDatasetId = ref("");
const deleteError = ref("");

// Dataset-list request state, so a failed load is not mistaken for an
// empty registry and the empty state doesn't flash while it's pending.
const datasetsLoading = ref(false);
const datasetsLoadError = ref("");

// =========================================================
// ANALYSIS CONTEXT (mode + selected dataset_ids)
// =========================================================
//
// `primaryDatasetId` is the dataset driving every dataset-dependent
// panel below (Overview, Preview, Schema, Ask Your Data execution) -
// in SINGLE mode it's the only selected dataset; in COMPARISON /
// CROSS_DATASET it's the anchor dataset until real multi-dataset
// execution exists (Step 2+).

const {
    mode: analysisMode,
    datasetIds: selectedDatasetIds,
    primaryDatasetId: selectedDatasetId,
    analysisContext,
    isSelected: isDatasetSelected,
    selectSingle: selectDatasetSingle,
    toggleDataset: toggleDatasetSelection,
    setMode: setAnalysisMode,
} = useAnalysisContext();

const analysisModeOptions = [
    { value: ANALYSIS_MODES.SINGLE, label: ANALYSIS_MODE_LABELS[ANALYSIS_MODES.SINGLE] },
    // COMPARISON / CROSS_DATASET stay defined in useAnalysisContext but are
    // not exposed until real multi-dataset execution exists.
];

const selectedDataset = computed(() =>
    datasets.value.find(
        (dataset) => dataset.dataset_id === selectedDatasetId.value,
    ) || null,
);

// Resolves the selected dataset_ids to their dataset entries through
// the existing dataset store - no separate/duplicated dataset list.
const selectedDatasetEntries = computed(() =>
    selectedDatasetIds.value
        .map((id) => datasets.value.find((dataset) => dataset.dataset_id === id))
        .filter(Boolean),
);

const selectedDatasetNames = computed(() =>
    selectedDatasetEntries.value.map((dataset) => dataset.filename),
);

const analysisModeLabel = computed(
    () => ANALYSIS_MODE_LABELS[analysisMode.value] || analysisMode.value,
);

// Drives the header status pill - kept in sync with the same
// selection state the sidebar's mode selector / status panel and
// the Ask Your Data banner already read from, instead of a static
// label that never reflected what's actually selected.
const headerStatusText = computed(() => {
    if (!selectedDatasetEntries.value.length) {
        return "No Dataset Loaded";
    }

    if (analysisMode.value === ANALYSIS_MODES.SINGLE) {
        return "Dataset Loaded";
    }

    return `${analysisModeLabel.value} · ${selectedDatasetEntries.value.length} Datasets`;
});

// Shell empty state when datasets exist but none is selected.
const emptySelectionText = computed(() => {
    const count = datasets.value.length;
    const noun = count === 1 ? "dataset" : "datasets";
    return isMobile.value
        ? `You have ${count} ${noun}. Open the library to pick one.`
        : `You have ${count} ${noun}. Pick one from Datasets in the sidebar.`;
});

function formatNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : "—";
}

// =========================================================
// DATASET UPLOAD / SELECTION
// =========================================================

// Every dataset-dependent panel keys off `selectedDatasetId`
// (the primary/anchor dataset), so remounting/resetting only needs
// to react to that changing, regardless of which selection path
// (single click, checkbox toggle, mode switch) caused it.
watch(selectedDatasetId, (newId, oldId) => {
    if (newId === oldId) {
        return;
    }

    // Force every dataset-dependent panel to remount against the
    // newly selected dataset_id instead of reusing state (and any
    // still-in-flight requests) built for the previous one.
    refreshKey.value += 1;

    selectedQuestion.value = "";
    question.value = "";
    error.value = null;
    result.value = null;
    deleteError.value = "";
});

// Evicts the dataset's cached GETs before the selection changes, so the
// remounted panels re-verify it with the server instead of reusing
// responses cached before it may have been deleted elsewhere - the
// quality audit included: selecting a dataset sends no request any more
// (every panel loads on demand), so nothing would re-verify a kept
// audit. Re-opening Quality re-requests it; the server answers from its
// own cache without recomputing.
//
// Requests still in flight stay shared (keepInFlight), so re-selecting a
// dataset whose metadata/audit is still running never sends a duplicate.
// Such a request still 404s on its own for a deleted dataset, which
// evicts everything through api.js.
function selectDataset(datasetId) {
    evictDatasetCache(datasetId, { keepInFlight: true });

    if (analysisMode.value === ANALYSIS_MODES.SINGLE) {
        selectDatasetSingle(datasetId);
    } else {
        toggleDatasetSelection(datasetId);
    }
}

function handleDatasetUploaded(uploadResponse) {
    const datasetId = uploadResponse?.dataset_id;

    if (!datasetId) {
        return;
    }

    const entry = {
        dataset_id: datasetId,
        filename: uploadResponse.filename || "Uploaded dataset",
        rows: uploadResponse.rows,
        columns: uploadResponse.columns,
    };

    const existingIndex = datasets.value.findIndex(
        (dataset) => dataset.dataset_id === datasetId,
    );

    if (existingIndex >= 0) {
        datasets.value.splice(existingIndex, 1, entry);
    } else {
        datasets.value.push(entry);
    }

    // A newly uploaded dataset always becomes active: in SINGLE mode
    // it replaces the current selection; in COMPARISON / CROSS_DATASET
    // it's added to the active set.
    selectDataset(datasetId);
}

// Hydrates the sidebar from the backend registry so datasets survive
// a page reload. Merged by dataset_id: an entry already present (e.g.
// uploaded while this request was in flight) is kept as-is. Nothing
// is auto-selected here. A failure only sets datasetsLoadError - the
// entries already listed are left untouched.
async function loadDatasets() {
    if (datasetsLoading.value) {
        return;
    }

    datasetsLoading.value = true;
    datasetsLoadError.value = "";

    try {
        const response = await listDatasets();
        const summaries = Array.isArray(response?.datasets) ? response.datasets : [];

        for (const summary of summaries) {
            if (!summary?.dataset_id) {
                continue;
            }

            const alreadyListed = datasets.value.some(
                (dataset) => dataset.dataset_id === summary.dataset_id,
            );

            if (!alreadyListed) {
                datasets.value.push({
                    dataset_id: summary.dataset_id,
                    filename: summary.filename || "Uploaded dataset",
                    rows: summary.rows,
                    columns: summary.columns,
                    created_at: summary.created_at,
                });
            }
        }

        // Nothing selected yet (typically: a page reload) - let the
        // selection policy decide whether a dataset opens automatically.
        // Goes through selectDataset(), exactly like a click.
        if (!selectedDatasetId.value) {
            const initialId = pickInitialDatasetId(datasets.value);
            if (initialId && datasets.value.some((d) => d.dataset_id === initialId)) {
                selectDataset(initialId);
            }
        }
    } catch (err) {
        console.error("Dataset list error:", err);
        datasetsLoadError.value =
            getApiErrorMessage(err) || "Unable to load datasets.";
    } finally {
        datasetsLoading.value = false;
    }
}

// A dataset-scoped request returned 404: the dataset is gone from the
// backend, so drop it from the list and from the selection. api.js has
// already evicted its cached responses. Clearing selectedDatasetId
// triggers the watcher above, which remounts every panel.
function handleDatasetMissing(datasetId) {
    datasets.value = datasets.value.filter(
        (dataset) => dataset.dataset_id !== datasetId,
    );

    if (selectedDatasetIds.value.includes(datasetId)) {
        selectedDatasetIds.value = selectedDatasetIds.value.filter(
            (id) => id !== datasetId,
        );
    }

    if (selectedDatasetId.value === datasetId) {
        selectedDatasetId.value = selectedDatasetIds.value[0] || "";
    }
}

// Deletes a dataset from the backend after confirmation, then reuses
// handleDatasetMissing() for the local cleanup (list, selection, panel
// reset). A 404 means it was already deleted elsewhere, so it's treated
// as success. Any other failure leaves the list and selection as-is.
async function handleDeleteDataset(dataset) {
    deleteError.value = "";

    if (deletingDatasetId.value) {
        return;
    }

    const confirmed = window.confirm(
        `Delete "${dataset.filename}"? This cannot be undone.`,
    );

    if (!confirmed) {
        return;
    }

    deletingDatasetId.value = dataset.dataset_id;

    try {
        await deleteDataset(dataset.dataset_id);
        handleDatasetMissing(dataset.dataset_id);
    } catch (err) {
        if (err?.response?.status === 404) {
            handleDatasetMissing(dataset.dataset_id);
        } else {
            console.error("Dataset delete error:", err);
            deleteError.value = getApiErrorMessage(err);
        }
    } finally {
        deletingDatasetId.value = "";
    }
}

let stopDatasetMissing = null;

onMounted(() => {
    stopDatasetMissing = onDatasetMissing(handleDatasetMissing);
    loadDatasets();
});

onBeforeUnmount(() => {
    stopDatasetMissing?.();
});

function setActiveSection(section) {
    activeSection.value = section;
}


async function handleQuestionSelected(newQuestion) {
    if (!newQuestion) {
        return;
    }

    // Reset first so re-selecting the same suggestion (e.g. after the
    // user cleared or edited it in AnalyticsBuilder) still changes the
    // prop and re-fills the question there. AnalyticsBuilder ignores "".
    selectedQuestion.value = "";
    await nextTick();

    selectedQuestion.value = newQuestion;
    question.value = newQuestion;

    error.value = null;
    result.value = null;

    // Workspace Phase 1: the question box now lives in the Analyze tab
    // (it was on the same long page before), so show that tab first;
    // the existing scroll below then brings it into view.
    setWorkspaceTab("analyze");

    nextTick(() => {
        const askDataSection =
            document.getElementById("ask-data");

        if (askDataSection) {
            askDataSection.scrollIntoView({
                behavior: "smooth",
                block: "start",
            });
        }
    });
}


watch(
    () => props.incomingQuestion,
    (newQuestion) => {
        if (!newQuestion) {
            return;
        }

        handleQuestionSelected(newQuestion);
    },
    {
        immediate: true,
    },
);
</script>

<template>
    <!-- =========================================================
         WORKSPACE SHELL (visual redesign, Stage 1)
         The Tabs root wraps the whole shell, so the section navigation
         can live in the forest sidebar (desktop) or the bottom bar
         (mobile) while the tab panels stay put in the workspace. Panels
         are never moved or remounted by a breakpoint change, so the
         analysis state survives resizing.
    ========================================================== -->

    <Tabs :model-value="workspaceTab" :items="WORKSPACE_TAB_ITEMS" label="Workspace" variant="none"
        :orientation="isMobile ? 'horizontal' : 'vertical'"
        class="flex h-dvh overflow-hidden bg-canvas text-ink" @update:model-value="setWorkspaceTab">

        <!-- ===== Sidebar (laptop + desktop) ===== -->

        <aside v-if="!isMobile" aria-label="Workspace navigation" class="w-sidebar shrink-0">
            <AppSidebar :user="user" :signing-out="signingOut" @logout="emit('logout')">
                <template #nav>
                    <TabNav :items="WORKSPACE_TAB_ITEMS" label="Workspace sections" variant="sidebar" />
                </template>
                <DatasetLibrary :datasets="datasets" :is-selected="isDatasetSelected" :format-number="formatNumber"
                    :analysis-mode="analysisMode" :analysis-mode-options="analysisModeOptions"
                    :analysis-mode-label="analysisModeLabel" :selected-dataset-entries="selectedDatasetEntries"
                    :selected-dataset-names="selectedDatasetNames" :datasets-loading="datasetsLoading"
                    :datasets-load-error="datasetsLoadError" :deleting-dataset-id="deletingDatasetId"
                    :delete-error="deleteError" @select="selectDataset" @delete="handleDeleteDataset"
                    @retry="loadDatasets" @upload="openUpload" @set-mode="setAnalysisMode" />
            </AppSidebar>
        </aside>

        <!-- ===== Workspace ===== -->

        <div class="flex min-w-0 flex-1 flex-col">

            <!-- Mobile top bar: menu (drawer), brand, account -->

            <header v-if="isMobile"
                class="grid h-14 shrink-0 grid-cols-[40px_1fr_40px] items-center gap-2 bg-topbar px-3">
                <button type="button" aria-label="Open datasets and account" aria-haspopup="dialog"
                    :aria-expanded="libraryOverlayOpen"
                    class="grid h-10 w-10 place-items-center rounded-full text-ink transition-colors duration-150 hover:bg-sunken"
                    @click="libraryOverlayOpen = true">
                    <Icon name="menu" :size="20" />
                </button>
                <span class="flex min-w-0 justify-center">
                    <BrandMark tone="ivory" :tagline="false" />
                </span>
                <AccountMenu v-if="user" :user="user" :signing-out="signingOut" side="bottom" align="end"
                    @logout="emit('logout')">
                    <button type="button" aria-label="Account menu"
                        class="grid h-9 w-9 place-items-center rounded-full bg-[#3f6b47] text-caption font-semibold text-on-forest ring-2 ring-[#cfe0cc]">
                        {{ userInitials }}
                    </button>
                </AccountMenu>
            </header>

            <h1 class="sr-only">Workspace</h1>

            <!-- Dataset context (every section) -->

            <ContextBar :key="`context-${refreshKey}`" :dataset-id="selectedDatasetId" :dataset="selectedDataset"
                :compact="isMobile" :has-datasets="datasets.length > 0" :datasets="datasets" :user="user"
                :signing-out="signingOut" @switch-dataset="openLibrary" @select="selectDataset"
                @upload="openUpload" @open-quality="setWorkspaceTab('quality')" @logout="emit('logout')" />

            <!-- Mobile section tabs (as in the reference). Plain buttons
                 driving the same tab state as the bottom bar, which is the
                 Reka tablist - two tablists would duplicate element ids. -->
            <nav v-if="isMobile" aria-label="Sections" class="shrink-0 border-b border-line bg-topbar px-2">
                <div class="grid grid-cols-4">
                    <button v-for="item in WORKSPACE_TAB_ITEMS" :key="item.value" type="button"
                        :aria-current="workspaceTab === item.value ? 'page' : undefined"
                        class="h-11 border-b-2 text-data transition-colors duration-150"
                        :class="workspaceTab === item.value
                            ? 'border-ink font-semibold text-ink'
                            : 'border-transparent font-medium text-ink-muted hover:text-ink'"
                        @click="setWorkspaceTab(item.value)">
                        {{ item.label }}
                    </button>
                </div>
            </nav>

            <!-- Section panels: always mounted; only the visible one shows. -->

            <div ref="sectionScroller" class="min-h-0 flex-1 overflow-y-auto"
                :class="isMobile ? 'pb-[calc(4.5rem+env(safe-area-inset-bottom))]' : ''">

                <!-- ANALYZE -->

                <!-- Fills the viewport height on laptop/desktop (chart, table
                     and inspector scroll inside it); flows naturally on mobile. -->
                <TabPanel value="analyze" :class="isMobile ? '' : 'h-full'">
                    <div class="flex min-h-0 flex-col" :class="isMobile ? '' : 'h-full'">

                        <!-- id kept: handleQuestionSelected scrolls here. The builder
                             renders its own canvas + findings inspector. -->
                        <section id="ask-data" class="flex min-h-0 scroll-mt-4 flex-col" :class="isMobile ? '' : 'flex-1'">
                            <AnalyticsBuilder :key="`builder-${refreshKey}`" class="flex-1"
                                :incoming-question="selectedQuestion" :dataset-id="selectedDatasetId"
                                :analysis-mode="analysisMode" :selected-dataset-ids="selectedDatasetIds"
                                :selected-dataset-names="selectedDatasetNames">
                                <!-- Shown by the builder when no dataset is selected:
                                     nothing uploaded yet / datasets exist but none is
                                     selected (nothing while the list is still loading). -->
                                <template #empty>
                                    <div v-if="!datasetsLoadError && !datasetsLoading"
                                        class="relative overflow-hidden rounded-panel border border-line bg-surface shadow-panel">
                                        <div aria-hidden="true"
                                            class="pointer-events-none absolute -right-20 -top-28 h-64 w-64 rounded-full bg-forest-soft blur-2xl">
                                        </div>
                                        <EmptyState v-if="!datasets.length" class="relative" icon="upload"
                                            title="Upload a dataset to begin"
                                            description="Add a CSV file. You can then ask questions in plain language, browse rows, review the schema and check data quality.">
                                            <template #action>
                                                <Button variant="primary" icon="upload" @click="openUpload">
                                                    Upload CSV
                                                </Button>
                                            </template>
                                        </EmptyState>
                                        <EmptyState v-else class="relative" icon="database" title="Choose a dataset to analyze"
                                            :description="emptySelectionText">
                                            <template v-if="isMobile" #action>
                                                <Button variant="primary" icon="database" @click="openLibrary">
                                                    Choose dataset
                                                </Button>
                                            </template>
                                        </EmptyState>
                                    </div>
                                </template>
                            </AnalyticsBuilder>
                        </section>

                    </div>
                </TabPanel>

                <!-- DATA -->

                <TabPanel value="data" :class="isMobile ? '' : 'h-full'">
                    <DataPreview :key="`preview-${refreshKey}`" :dataset-id="selectedDatasetId"
                        :active="workspaceTab === 'data'" />
                </TabPanel>

                <!-- SCHEMA -->

                <TabPanel value="schema">
                    <div class="w-full max-w-[1400px] px-4 pb-6 pt-5 sm:px-6 lg:px-9 lg:pt-7">
                        <DatasetMetadata :key="`metadata-${refreshKey}`" :dataset-id="selectedDatasetId"
                            :active="workspaceTab === 'schema'" @question-selected="handleQuestionSelected" />
                    </div>
                </TabPanel>

                <!-- QUALITY -->

                <TabPanel value="quality">
                    <div class="w-full max-w-[1400px] px-4 pb-6 pt-5 sm:px-6 lg:px-9 lg:pt-7">
                        <DataQuality :key="`quality-${refreshKey}`" :dataset-id="selectedDatasetId"
                            :active="workspaceTab === 'quality'" />
                    </div>
                </TabPanel>

            </div>

        </div>

        <!-- ===== Mobile bottom section bar ===== -->

        <nav v-if="isMobile" aria-label="Workspace sections"
            class="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur">
            <TabNav :items="WORKSPACE_TAB_ITEMS" label="Workspace sections" variant="bottom" />
        </nav>

        <!-- ===== Mobile navigation drawer: brand, library, account ===== -->

        <Dialog v-if="isMobile" :open="libraryOverlayOpen" title="Datasets"
            description="Choose the dataset to work with, or upload a new one." hide-title side="left" tone="forest"
            width="w-[min(88vw,320px)]" body-class="flex flex-col p-0" @update:open="libraryOverlayOpen = $event">
            <AppSidebar :user="user" :signing-out="signingOut" class="flex-1" @logout="emit('logout')">
                <DatasetLibrary :datasets="datasets" :is-selected="isDatasetSelected" :format-number="formatNumber"
                    :analysis-mode="analysisMode" :analysis-mode-options="analysisModeOptions"
                    :analysis-mode-label="analysisModeLabel" :selected-dataset-entries="selectedDatasetEntries"
                    :selected-dataset-names="selectedDatasetNames" :datasets-loading="datasetsLoading"
                    :datasets-load-error="datasetsLoadError" :deleting-dataset-id="deletingDatasetId"
                    :delete-error="deleteError" touch @select="chooseDataset" @delete="handleDeleteDataset"
                    @retry="loadDatasets" @upload="openUpload" @set-mode="setAnalysisMode" />
            </AppSidebar>
        </Dialog>

        <!-- Upload (sidebar, drawer, context bar, empty state, #upload) -->

        <Dialog :open="uploadOpen" title="Upload dataset"
            description="Add a CSV file to explore it and ask questions of it." hide-title
            :side="isMobile ? 'bottom' : 'center'" width="max-w-xl" content-class="bg-canvas"
            @update:open="uploadOpen = $event">
            <DatasetUpload :active-dataset="selectedDataset" @dataset-uploaded="handleDatasetUploaded" />
        </Dialog>

    </Tabs>
</template>
