<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { datasetUrls, getCachedResponse, onCachedResponse } from "../../services/api";
import Button from "../ui/Button.vue";
import Icon from "../ui/Icon.vue";
import Menu from "../ui/Menu.vue";
import Tooltip from "../ui/Tooltip.vue";
import { initials } from "../../services/userDisplay";
import { healthScore, scoreBand } from "../../services/qualityScore";
import AccountMenu from "./AccountMenu.vue";

// =========================================================
// DATASET CONTEXT BAR
// =========================================================
//
// The selected dataset's vital signs, visible from every workspace tab.
//
// This bar sends NO requests of its own. Selecting a dataset must not
// start expensive server-side builds (they run on the bounded analysis
// worker pool and hold the dataset's locks, delaying the user's own
// questions):
//
// - name, rows and columns come from the dataset list entry (the
//   `dataset` prop - the backend's dataset summary), never /profile;
// - the quality audit only runs when the user opens the Quality
//   workspace (see useQualityAudit). This bar reads an audit already in
//   the browser cache; until there is one it shows a neutral
//   "Not audited" pill that opens Quality.
//
// Dashboard keys this component by refreshKey, so it reloads when the
// dataset changes, and it follows an audit stored later (the Quality
// panel's load or Refresh) via onCachedResponse.
//
// (The memory pill was dropped with /profile: uploads are always
// disk-backed DuckDB datasets, which report 0 bytes, so it never showed.)

const props = defineProps({
    datasetId: { type: String, default: "" },
    // Entry from Dashboard's dataset list: { filename, rows, columns }.
    dataset: { type: Object, default: null },
    compact: { type: Boolean, default: false },
    // True when the user has datasets but none is selected; false when
    // the library is empty (the bar then offers an upload instead).
    hasDatasets: { type: Boolean, default: false },
    // Every dataset in the library (desktop name menu switches between them).
    datasets: { type: Array, default: () => [] },
    user: { type: Object, default: null },
    signingOut: { type: Boolean, default: false },
});

const emit = defineEmits(["open-quality", "switch-dataset", "upload", "select", "logout"]);

// Mobile: the vital signs open under the dataset row on demand.
const detailsOpen = ref(false);

// Desktop dataset menu: every dataset, plus "Upload dataset".
const datasetMenuItems = computed(() => [
    ...props.datasets.map((entry) => ({
        key: entry.dataset_id,
        label: entry.filename,
        icon: entry.dataset_id === props.datasetId ? "check" : "table",
    })),
    { separator: true },
    { key: "__upload", label: "Upload dataset", icon: "upload" },
]);

function onDatasetMenu(key) {
    if (key === "__upload") {
        emit("upload");
    } else if (key !== props.datasetId) {
        emit("select", key);
    }
}

const avatarInitials = computed(() => initials(props.user));

// Top-bar tools from the visual reference whose features are not built
// yet. Drawn exactly as designed, but inert (aria-disabled) and labelled
// "coming soon" so nothing pretends to work.
const PLANNED_TOOLS = [
    { icon: "search", label: "Search" },
    { icon: "help", label: "Help" },
    { icon: "bell", label: "Notifications" },
];

const quality = ref(null);

// Cache lookup only - no request (see the header comment).
onMounted(() => {
    if (props.datasetId) {
        quality.value = getCachedResponse(datasetUrls.quality(props.datasetId)) ?? null;
    }
});

// Follow an audit stored elsewhere (the Quality panel's load or its
// Refresh): when the cache stores a new response for THIS dataset's
// quality URL, show it. No request is sent from here.
const stopFollowingRefreshes = onCachedResponse((url, data) => {
    if (props.datasetId && url === datasetUrls.quality(props.datasetId)) {
        quality.value = data;
    }
});

onBeforeUnmount(stopFollowingRefreshes);

function formatCount(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString() : null;
}

const rows = computed(() => formatCount(props.dataset?.rows));
const columns = computed(() => formatCount(props.dataset?.columns));

const qualityStatus = computed(() => quality.value?.status || null);

// "Healthy", "Warning · 3 issues" - the backend's own status word plus
// its own issue count. There is no numeric score in the response, so
// none is shown.
const qualityLabel = computed(() => {
    if (!qualityStatus.value) {
        return "";
    }
    const word = qualityStatus.value.charAt(0).toUpperCase() + qualityStatus.value.slice(1);
    const count = Number(quality.value?.issue_count);
    return Number.isFinite(count) && count > 0
        ? `${word} · ${count.toLocaleString()} issue${count === 1 ? "" : "s"}`
        : word;
});

const PILL = "inline-flex h-8 shrink-0 items-center gap-1 rounded-[10px] border border-[#ebe3d2] bg-[#f4eee1] px-3 text-data text-ink";

const QUALITY_PILL = {
    success: { classes: "border-[#c9e2c1] bg-success-pill text-ink", icon: "check-circle", iconClass: "text-success-strong" },
    warning: { classes: "border-warn-ink/15 bg-warn-soft text-warn-ink", icon: "warning", iconClass: "" },
    error: { classes: "border-danger/15 bg-danger-soft text-danger", icon: "error", iconClass: "" },
    neutral: { classes: "border-line bg-sunken text-ink", icon: "info", iconClass: "text-ink-muted" },
};
// The pill shows the Quality screen's own health score (shared
// implementation) and takes its color from that score's band; the
// backend's status word and issue count stay in the tooltip.
const qualityScore = computed(() => (quality.value ? healthScore(quality.value) : null));
const BAND_TONE = { good: "success", fair: "warning", poor: "error" };
const qualityPill = computed(() => {
    const tone = quality.value?.status === "invalid" ? "error" : BAND_TONE[scoreBand(qualityScore.value)] || "neutral";
    return QUALITY_PILL[tone] || QUALITY_PILL.neutral;
});

// No audit in the browser cache yet: a neutral pill that opens Quality,
// where the audit is requested.
const NOT_AUDITED_TOOLTIP = "Quality not checked yet. Open Quality to run the audit.";
</script>

<template>
    <!-- =================== DESKTOP / LAPTOP =================== -->

    <div v-if="!compact" class="flex h-[60px] shrink-0 items-center gap-2 border-b border-[#ece4d4] bg-topbar px-6">

        <!-- No dataset selected -->
        <template v-if="!dataset">
            <span aria-hidden="true"
                class="grid h-8 w-8 shrink-0 place-items-center rounded-control border border-dashed border-line-strong text-ink-subtle">
                <Icon name="database" :size="16" />
            </span>
            <p class="min-w-0 truncate text-data text-ink-muted">
                <span class="font-medium text-ink">No dataset selected</span>
                <span v-if="hasDatasets"> · Choose one from the library</span>
            </p>
            <Button v-if="!hasDatasets" size="sm" variant="primary" icon="upload" class="ml-2" @click="emit('upload')">
                Upload CSV
            </Button>
        </template>

        <template v-else>
            <!-- Dataset name: menu to switch dataset -->
            <Menu :items="datasetMenuItems" align="start" @select="onDatasetMenu">
                <template #trigger>
                    <button type="button" :aria-label="`Dataset: ${dataset.filename}. Switch dataset`"
                        class="-ml-2 mr-3 flex min-w-0 max-w-[280px] items-center gap-1.5 rounded-control px-2 py-1.5 text-left transition-colors duration-150 hover:bg-sunken data-[state=open]:bg-sunken">
                        <span class="truncate text-[17px] font-semibold tracking-[-0.01em] text-ink">{{ dataset.filename }}</span>
                        <Icon name="chevron-down" :size="16" class="text-ink" />
                    </button>
                </template>
            </Menu>

            <!-- Vital signs -->
            <dl class="flex min-w-0 items-center gap-2 overflow-hidden">
                <div v-if="rows" :class="PILL">
                    <dt class="order-last">rows</dt>
                    <dd class="tabular-nums">{{ rows }}</dd>
                </div>
                <div v-if="columns" :class="PILL">
                    <dt class="order-last">columns</dt>
                    <dd class="tabular-nums">{{ columns }}</dd>
                </div>
            </dl>

            <!-- Quality: opens the Quality section -->
            <Tooltip v-if="qualityStatus" :content="qualityScore === null ? qualityLabel : `Health score ${qualityScore}%, calculated in the app from the audit's issues · audit status: ${qualityLabel}`">
                <button type="button" :aria-label="`Data quality: ${qualityScore === null ? qualityLabel : `${qualityScore}% (${qualityLabel})`}. Open Quality`"
                    class="ml-0.5 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[10px] border px-3 text-data font-semibold transition-[filter] duration-150 hover:brightness-[0.98]"
                    :class="qualityPill.classes" @click="emit('open-quality')">
                    <Icon :name="qualityPill.icon" :size="16" :class="qualityPill.iconClass" />
                    Quality: {{ qualityScore === null ? qualityLabel.split(' · ')[0] : `${qualityScore}%` }}
                </button>
            </Tooltip>
            <Tooltip v-else-if="datasetId" :content="NOT_AUDITED_TOOLTIP">
                <button type="button" aria-label="Data quality: not audited. Open Quality"
                    class="ml-0.5 inline-flex h-8 shrink-0 items-center gap-1.5 rounded-[10px] border px-3 text-data font-semibold transition-[filter] duration-150 hover:brightness-[0.98]"
                    :class="QUALITY_PILL.neutral.classes" @click="emit('open-quality')">
                    <Icon :name="QUALITY_PILL.neutral.icon" :size="16" :class="QUALITY_PILL.neutral.iconClass" />
                    Quality: Not audited
                </button>
            </Tooltip>
        </template>

        <!-- Tools + account -->
        <div class="ml-auto flex shrink-0 items-center gap-1">
            <Tooltip v-for="tool in PLANNED_TOOLS" :key="tool.icon" :content="`${tool.label} - coming soon`">
                <button type="button" :aria-label="`${tool.label} (coming soon)`" aria-disabled="true"
                    class="grid h-10 w-10 cursor-default place-items-center rounded-full text-ink">
                    <Icon :name="tool.icon" :size="20" />
                </button>
            </Tooltip>
            <AccountMenu v-if="user" :user="user" :signing-out="signingOut" side="bottom" align="end"
                @logout="emit('logout')">
                <button type="button" aria-label="Account menu"
                    class="ml-2 grid h-10 w-10 place-items-center rounded-full bg-[#8c7340] text-data font-semibold text-[#fbf3df] ring-2 ring-[#e6d6ad] transition-[filter] duration-150 hover:brightness-110">
                    {{ avatarInitials }}
                </button>
            </AccountMenu>
        </div>

    </div>

    <!-- ======================== MOBILE ======================== -->

    <template v-else>
        <div class="flex min-h-[52px] shrink-0 items-center gap-2 bg-topbar px-4 py-1.5">

            <template v-if="!dataset">
                <p class="min-w-0 flex-1 truncate text-data font-medium text-ink">No dataset selected</p>
                <Button v-if="hasDatasets" size="sm" icon="database" @click="emit('switch-dataset')">Choose</Button>
                <Button v-else size="sm" variant="primary" icon="upload" @click="emit('upload')">Upload CSV</Button>
            </template>

            <template v-else>
                <button type="button" aria-haspopup="dialog" :aria-label="`Dataset: ${dataset.filename}. Switch dataset`"
                    class="flex min-w-0 items-center gap-1.5 rounded-[10px] bg-[#f1ebdd] px-2.5 py-1.5 text-left"
                    @click="emit('switch-dataset')">
                    <Icon name="table" :size="16" class="text-[#a98a4f]" />
                    <span class="truncate text-data font-semibold text-ink">{{ dataset.filename }}</span>
                    <Icon name="chevron-down" :size="14" class="text-ink" />
                </button>
                <button type="button" :aria-expanded="detailsOpen" aria-controls="mobile-dataset-details"
                    :aria-label="detailsOpen ? 'Hide dataset details' : 'Show dataset details'"
                    class="ml-auto grid h-9 w-9 place-items-center rounded-full text-ink hover:bg-sunken"
                    @click="detailsOpen = !detailsOpen">
                    <Icon name="chevron-down" :size="16" class="transition-transform duration-150"
                        :class="detailsOpen ? 'rotate-180' : ''" />
                </button>
            </template>
        </div>

        <dl v-if="dataset && detailsOpen" id="mobile-dataset-details"
            class="flex shrink-0 flex-wrap gap-1.5 bg-topbar px-4 pb-2.5">
            <div v-if="rows" :class="PILL">
                <dt class="order-last">rows</dt>
                <dd class="tabular-nums">{{ rows }}</dd>
            </div>
            <div v-if="columns" :class="PILL">
                <dt class="order-last">columns</dt>
                <dd class="tabular-nums">{{ columns }}</dd>
            </div>
            <button v-if="qualityStatus" type="button"
                class="inline-flex h-8 items-center gap-1.5 rounded-[10px] border px-3 text-data font-semibold"
                :class="qualityPill.classes" @click="emit('open-quality')">
                <Icon :name="qualityPill.icon" :size="16" :class="qualityPill.iconClass" />
                Quality: {{ qualityScore === null ? qualityLabel.split(' · ')[0] : `${qualityScore}%` }}
            </button>
            <button v-else-if="datasetId" type="button" aria-label="Data quality: not audited. Open Quality"
                class="inline-flex h-8 items-center gap-1.5 rounded-[10px] border px-3 text-data font-semibold"
                :class="QUALITY_PILL.neutral.classes" @click="emit('open-quality')">
                <Icon :name="QUALITY_PILL.neutral.icon" :size="16" :class="QUALITY_PILL.neutral.iconClass" />
                Quality: Not audited
            </button>
        </dl>
    </template>
</template>
