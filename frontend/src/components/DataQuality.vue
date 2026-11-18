<script setup>
import { ref, computed, onMounted } from "vue";
import { getDatasetQuality, getApiErrorMessage } from "../services/api";
import { healthScore as computeHealthScore, scoreBand, severityCounts } from "../services/qualityScore";
import Button from "./ui/Button.vue";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";

// Scoped to an explicit dataset like the other panels - the
// un-scoped /dataset/quality route reads the server's global
// "active dataset" instead.
const props = defineProps({
    datasetId: {
        type: String,
        default: null,
    },
});

const loading = ref(true);
const error = ref(null);
const qualityData = ref(null);
// Severity filter for the issue list (as before the redesign).
const activeFilter = ref("all");

// Same score as before (now shared with the top bar's quality pill).
const healthScore = computed(() => computeHealthScore(qualityData.value));
const band = computed(() => scoreBand(healthScore.value));
const counts = computed(() => severityCounts(qualityData.value));

const BAND_TEXT = {
    unknown: "No quality score is available for this audit.",
    good: "Your dataset is in good shape.",
    fair: "A few issues need attention.",
    poor: "Significant issues need attention.",
};

// Score ring geometry (SVG circle, r = 52).
const RING = 2 * Math.PI * 52;
const ringOffset = computed(() => RING * (1 - (healthScore.value ?? 0) / 100));
const RING_COLOR = { good: "#2c7d3f", fair: "#c27c12", poor: "#c2412d", unknown: "#cfc5af" };

const issues = computed(() => qualityData.value?.issues || []);

const filteredIssues = computed(() =>
    activeFilter.value === "all" ? issues.value : issues.value.filter((issue) => issue.severity === activeFilter.value),
);

const ISSUE_FILTERS = computed(() => [
    { id: "all", label: `All (${issues.value.length})` },
    { id: "warning", label: "Warnings" },
    { id: "info", label: "Info" },
]);

function issuesOfType(...types) {
    return issues.value.filter((issue) => types.includes(issue.type));
}

function sumCounts(list) {
    return list.reduce((sum, issue) => sum + (Number(issue.count) || 0), 0);
}

function columnsLabel(list) {
    const columns = new Set(list.map((issue) => issue.column).filter(Boolean));
    return `${columns.size} ${columns.size === 1 ? "column" : "columns"}`;
}

// Issue summary: one row per check the backend runs. Figures are the
// backend's own issue counts - nothing is estimated here.
const summaryRows = computed(() => {
    const missing = issuesOfType("missing_values");
    const duplicates = issuesOfType("duplicate_rows");
    const structure = issuesOfType("constant_column", "high_cardinality");
    const outliers = issuesOfType("numeric_outliers");
    return [
        { key: "missing", label: "Missing values", scope: columnsLabel(missing), value: `${sumCounts(missing).toLocaleString()} cells`, flagged: missing.length > 0 },
        { key: "duplicates", label: "Duplicate rows", scope: `${sumCounts(duplicates).toLocaleString()} rows`, value: duplicates.length ? "Found" : "None", flagged: duplicates.length > 0 },
        { key: "structure", label: "Column structure", scope: columnsLabel(structure), value: structure.length ? `${structure.length} flagged` : "None", flagged: structure.length > 0 },
        { key: "outliers", label: "Outliers (distribution)", scope: columnsLabel(outliers), value: `${sumCounts(outliers).toLocaleString()} values`, flagged: outliers.length > 0 },
    ];
});

const SEVERITY_STYLE = {
    error: { icon: "error", tile: "bg-[#fbe4df] text-[#c2412d]" },
    warning: { icon: "warning", tile: "bg-[#fbecd6] text-[#c27012]" },
    info: { icon: "info", tile: "bg-[#e3eef8] text-[#2f6fae]" },
};

function severityStyle(issue) {
    return SEVERITY_STYLE[issue.severity] || SEVERITY_STYLE.info;
}

// Phase 6: `refresh` bypasses the client cache (api.js cachedGet), the
// same pattern as DatasetOverview/DataPreview/DatasetMetadata. Without
// it the Refresh button re-read the cached response and never re-ran
// the audit. Initial load is unchanged (cached).
async function fetchQuality(options = {}) {
    loading.value = true;
    error.value = null;

    try {
        const data = await getDatasetQuality(props.datasetId, {
            force: options.refresh === true,
        });
        qualityData.value = data;
    } catch (err) {
        error.value = getApiErrorMessage(err);
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    if (props.datasetId) {
        fetchQuality();
    } else {
        loading.value = false;
    }
});
</script>

<template>
    <section aria-labelledby="quality-title" class="flex flex-col gap-5">

        <!-- Header -->
        <header class="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 id="quality-title" class="text-[28px] font-bold leading-tight tracking-[-0.02em] text-ink">Data Quality</h2>
                <p class="mt-1 text-body text-ink-muted">Automated checks for integrity, consistency and distribution.</p>
            </div>
            <Button v-if="datasetId" icon="refresh" :loading="loading" class="h-10 rounded-[10px] bg-surface px-4"
                @click="fetchQuality({ refresh: true })">
                Refresh
            </Button>
        </header>

        <!-- No dataset selected -->
        <div v-if="!datasetId" class="rounded-[16px] border border-[#e6decd] bg-surface">
            <EmptyState icon="shield-check" title="No dataset selected"
                description="Upload or select a dataset to audit its quality." />
        </div>

        <!-- Loading -->
        <div v-else-if="loading" role="status"
            class="flex h-48 items-center justify-center gap-3 rounded-[16px] border border-[#e6decd] bg-surface text-data text-ink-muted">
            <span aria-hidden="true" class="h-5 w-5 animate-spin rounded-full border-2 border-forest/20 border-t-forest"></span>
            Auditing dataset quality…
        </div>

        <!-- Error -->
        <p v-else-if="error" role="alert"
            class="flex items-start gap-2.5 rounded-[14px] border border-danger/20 bg-danger-soft px-4 py-3 text-data text-danger">
            <Icon name="error" :size="16" class="mt-0.5" />
            <span>{{ error }}</span>
        </p>

        <template v-else>

            <!-- Overview: score ring + severity counts -->
            <div
                class="grid gap-5 rounded-[16px] border border-[#e6decd] bg-surface p-5 shadow-panel lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)] lg:items-center">

                <div class="flex items-center gap-5 lg:border-r lg:border-[#ece5d6] lg:pr-5">
                    <div class="relative h-[120px] w-[120px] shrink-0" role="img"
                        :aria-label="healthScore === null ? 'Overall quality score unavailable' : `Overall quality score ${healthScore} percent`">
                        <svg viewBox="0 0 120 120" class="h-full w-full -rotate-90">
                            <circle cx="60" cy="60" r="52" fill="none" stroke="#e7efe2" stroke-width="12" />
                            <circle cx="60" cy="60" r="52" fill="none" :stroke="RING_COLOR[band]" stroke-width="12"
                                stroke-linecap="round" :stroke-dasharray="RING" :stroke-dashoffset="ringOffset" />
                        </svg>
                        <span class="absolute inset-0 grid place-items-center text-[26px] font-bold tabular-nums text-ink">
                            {{ healthScore === null ? "—" : `${healthScore}%` }}
                        </span>
                    </div>
                    <div>
                        <p class="text-[20px] font-bold tracking-[-0.01em] text-ink">Overall Quality</p>
                        <p class="mt-1 text-data text-ink-muted">{{ BAND_TEXT[band] }}</p>
                        <p class="mt-1 text-caption text-ink-subtle">
                            Score calculated in the app from the issues below (critical −25, warning −10,
                            info −3). Audit status: {{ qualityData?.status || "unknown" }}
                        </p>
                    </div>
                </div>

                <dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <div class="rounded-[12px] bg-[#fbf1e3] px-3 py-4 text-center">
                        <dd class="text-[34px] font-semibold leading-none tabular-nums text-[#d9771c]">{{ counts.total }}</dd>
                        <dt class="mt-2 text-data font-medium text-[#b8641a]">Issues</dt>
                    </div>
                    <div class="rounded-[12px] bg-[#fbe6e2] px-3 py-4 text-center">
                        <dd class="text-[34px] font-semibold leading-none tabular-nums text-[#d23a2a]">{{ counts.error }}</dd>
                        <dt class="mt-2 text-data font-medium text-ink">Critical</dt>
                    </div>
                    <div class="rounded-[12px] bg-[#f8efdc] px-3 py-4 text-center">
                        <dd class="text-[34px] font-semibold leading-none tabular-nums text-[#c27c12]">{{ counts.warning }}</dd>
                        <dt class="mt-2 text-data font-medium text-[#9c6510]">Warnings</dt>
                    </div>
                    <div class="rounded-[12px] bg-[#e9f1f8] px-3 py-4 text-center">
                        <dd class="text-[34px] font-semibold leading-none tabular-nums text-[#2f86c8]">{{ counts.info }}</dd>
                        <dt class="mt-2 text-data font-medium text-[#2a6ea6]">Info</dt>
                    </div>
                </dl>
            </div>

            <div class="grid gap-5 lg:grid-cols-2">

                <!-- Issue summary -->
                <section aria-labelledby="issue-summary-title"
                    class="rounded-[16px] border border-[#e6decd] bg-surface px-5 pb-3 pt-4 shadow-panel">
                    <h3 id="issue-summary-title" class="text-lead font-semibold text-ink">Issue Summary</h3>
                    <table class="mt-3 w-full text-left text-data">
                        <caption class="sr-only">Checks run by the audit and what they found</caption>
                        <tbody>
                            <tr v-for="row in summaryRows" :key="row.key" class="border-t border-[#ece5d6] first:border-t-0">
                                <th scope="row" class="py-2.5 pr-3 font-normal text-ink">
                                    <span class="flex items-center gap-2">
                                        <Icon :name="row.flagged ? 'warning' : 'check-circle'" :size="16"
                                            :class="row.flagged ? 'text-[#c27012]' : 'text-success'" />
                                        {{ row.label }}
                                    </span>
                                </th>
                                <td class="py-2.5 pr-3 text-ink-muted tabular-nums">{{ row.scope }}</td>
                                <td class="py-2.5 text-right tabular-nums text-ink">{{ row.value }}</td>
                            </tr>
                        </tbody>
                    </table>
                </section>

                <!-- Issues -->
                <section aria-labelledby="issues-title"
                    class="rounded-[16px] border border-[#e6decd] bg-surface px-5 pb-3 pt-4 shadow-panel">
                    <div class="flex flex-wrap items-center justify-between gap-2">
                        <h3 id="issues-title" class="text-lead font-semibold text-ink">
                            Issues <span class="tabular-nums">({{ issues.length }})</span>
                        </h3>
                        <div v-if="issues.length" class="flex items-center gap-0.5 rounded-control bg-sunken p-0.5" role="group"
                            aria-label="Filter issues by severity">
                            <button v-for="filter in ISSUE_FILTERS" :key="filter.id" type="button"
                                :aria-pressed="activeFilter === filter.id" @click="activeFilter = filter.id"
                                class="rounded-[6px] px-2.5 py-1 text-caption font-medium transition-colors duration-150"
                                :class="activeFilter === filter.id ? 'bg-surface text-ink shadow-panel' : 'text-ink-muted hover:text-ink'">
                                {{ filter.label }}
                            </button>
                        </div>
                    </div>
                    <EmptyState v-if="!issues.length" icon="check" title="No issues found"
                        description="Your dataset passes every check in this audit." />
                    <EmptyState v-else-if="!filteredIssues.length" icon="check" title="No issues found in this category"
                        description="Your dataset passes all corresponding validation checks." />
                    <ul v-else class="mt-2 max-h-[360px] overflow-y-auto [scrollbar-width:thin]">
                        <li v-for="(issue, index) in filteredIssues" :key="index" class="flex items-start gap-3 py-2.5">
                            <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full"
                                :class="severityStyle(issue).tile">
                                <Icon :name="severityStyle(issue).icon" :size="16" />
                                <span class="sr-only">{{ issue.severity }}</span>
                            </span>
                            <div class="min-w-0 pt-1">
                                <p class="text-data text-ink">{{ issue.message }}</p>
                                <p v-if="issue.column" class="mt-0.5 text-caption text-ink-muted">
                                    <span class="font-mono">{{ issue.column }}</span> · {{ issue.severity }}
                                </p>
                            </div>
                        </li>
                    </ul>
                </section>

            </div>

        </template>

    </section>
</template>
