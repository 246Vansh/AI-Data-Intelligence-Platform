<script setup>
import { computed, ref } from "vue";
import { useDatasetResource } from "../composables/useDatasetResource";
import { getDatasetMetadata, getApiErrorMessage } from "../services/api";
import Button from "./ui/Button.vue";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";

const emit = defineEmits(["question-selected"]);

const props = defineProps({
    datasetId: {
        type: String,
        default: "",
    },
    // True while the Schema workspace is the visible tab (see Dashboard).
    active: {
        type: Boolean,
        default: false,
    },
});

// Requested the first time the Schema tab is shown for this dataset,
// not when the panel mounts (it is mounted, hidden, from page load) -
// see useDatasetResource. /metadata is the same cached request the Data
// tab and the Analyze suggestions use (api.js cachedGet), so if either
// already loaded it, opening Schema sends nothing. Refresh bypasses the
// browser cache only; the server answers from its own cached metadata.
const metadataResource = useDatasetResource({
    datasetId: () => props.datasetId,
    active: () => props.active,
    fetch: (id, options) => getDatasetMetadata(id, options),
    errorMessage: (err) => getApiErrorMessage(err) || "Unable to load dataset metadata.",
});

const metadata = metadataResource.data;
const refreshing = metadataResource.refreshing;
const error = metadataResource.error;
// Also true before the first activation's request starts.
const loading = computed(() =>
    Boolean(props.datasetId) && (metadataResource.loading.value || !metadataResource.settled.value),
);
const searchQuery = ref("");
const copiedQuestion = ref(null);

function loadMetadata(options = {}) {
    return metadataResource.load(options);
}

const columns = computed(() => {
    if (!metadata.value?.columns) {
        return [];
    }

    return Object.entries(metadata.value.columns).map(
        ([name, column]) => ({
            name,
            ...column,
        }),
    );
});

const filteredColumns = computed(() => {
    const query = searchQuery.value.trim().toLowerCase();

    if (!query) {
        return columns.value;
    }

    return columns.value.filter((column) =>
        [column.name, column.role, roleLabel(column.role), column.data_type].some((value) =>
            String(value ?? "")
                .toLowerCase()
                .includes(query),
        ),
    );
});

const columnCount = computed(() => columns.value.length);
const visibleColumnCount = computed(() => filteredColumns.value.length);

const roleSummary = computed(() => {
    const summary = {};

    columns.value.forEach((column) => {
        const role = column.role || "unknown";
        summary[role] = (summary[role] || 0) + 1;
    });

    return summary;
});

const numericColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();
        const type = String(column.data_type || "").toLowerCase();

        return (
            role.includes("metric") ||
            role.includes("numeric") ||
            type.includes("int") ||
            type.includes("float") ||
            type.includes("double") ||
            type.includes("decimal") ||
            type.includes("number")
        );
    }),
);

const dimensionColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();

        return (
            role.includes("dimension") ||
            role.includes("categor")
        );
    }),
);

const dateColumns = computed(() =>
    columns.value.filter((column) => {
        const role = String(column.role || "").toLowerCase();
        const type = String(column.data_type || "").toLowerCase();

        return (
            role.includes("date") ||
            role.includes("time") ||
            type.includes("date") ||
            type.includes("time")
        );
    }),
);

const totalMissingValues = computed(() =>
    columns.value.reduce((total, column) => {
        const value = Number(column.missing_count);
        return total + (Number.isFinite(value) ? value : 0);
    }, 0),
);

const totalUniqueValues = computed(() =>
    columns.value.reduce((total, column) => {
        const value = Number(column.unique_values);
        return total + (Number.isFinite(value) ? value : 0);
    }, 0),
);

const backendQuestions = computed(() => {
    const candidates = [
        metadata.value?.example_questions,
        metadata.value?.suggested_questions,
        metadata.value?.sample_questions,
    ];

    for (const candidate of candidates) {
        if (!Array.isArray(candidate)) {
            continue;
        }

        const questions = candidate
            .map((item) => {
                if (typeof item === "string") {
                    return item;
                }

                if (typeof item?.question === "string") {
                    return item.question;
                }

                if (typeof item?.text === "string") {
                    return item.text;
                }

                return null;
            })
            .filter(Boolean)
            .map((question) => question.trim())
            .filter(Boolean);

        if (questions.length) {
            return questions;
        }
    }

    return [];
});

function prettyColumnName(name) {
    if (!name) {
        return "this field";
    }

    return String(name)
        .replace(/_/g, " ")
        .replace(/-/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

const generatedQuestions = computed(() => {
    const questions = [];
    const metric = numericColumns.value[0]?.name || null;
    const secondMetric = numericColumns.value[1]?.name || null;
    const dimension = dimensionColumns.value[0]?.name || null;
    const secondDimension = dimensionColumns.value[1]?.name || null;
    const date = dateColumns.value[0]?.name || null;

    if (metric) {
        questions.push(
            `What is the total ${prettyColumnName(metric)}?`,
            `What is the average ${prettyColumnName(metric)}?`,
            `What are the highest and lowest ${prettyColumnName(metric)} values?`,
        );
    }

    if (dimension && metric) {
        questions.push(
            `What are the top categories by ${prettyColumnName(metric)}?`,
            `Which ${prettyColumnName(dimension)} has the highest ${prettyColumnName(metric)}?`,
            `How does ${prettyColumnName(metric)} vary across ${prettyColumnName(dimension)}?`,
        );
    }

    if (date && metric) {
        questions.push(
            `How does ${prettyColumnName(metric)} change over time?`,
            `What is the trend of ${prettyColumnName(metric)} by ${prettyColumnName(date)}?`,
        );
    }

    if (
        secondDimension &&
        metric &&
        secondDimension !== dimension
    ) {
        questions.push(
            `Compare ${prettyColumnName(metric)} across ${prettyColumnName(dimension)} and ${prettyColumnName(secondDimension)}.`,
        );
    }

    if (
        metric &&
        secondMetric &&
        metric !== secondMetric
    ) {
        questions.push(
            `How are ${prettyColumnName(metric)} and ${prettyColumnName(secondMetric)} related?`,
        );
    }

    if (dimension && !metric) {
        questions.push(
            `What are the most common ${prettyColumnName(dimension)} values?`,
            `How many unique ${prettyColumnName(dimension)} values are there?`,
        );
    }

    if (date && !metric) {
        questions.push(
            "What time period does the dataset cover?",
            `How many records are available for each ${prettyColumnName(date)} period?`,
        );
    }

    if (!questions.length) {
        questions.push(
            "What are the main patterns in this dataset?",
            "What are the most important insights from this data?",
            "Are there any unusual or unexpected values?",
            "Can you summarize this dataset?",
        );
    }

    return [...new Set(questions)].slice(0, 8);
});

const exampleQuestions = computed(() =>
    backendQuestions.value.length
        ? backendQuestions.value.slice(0, 8)
        : generatedQuestions.value,
);

async function selectQuestion(question) {
    emit("question-selected", question);

    try {
        if (navigator?.clipboard?.writeText) {
            await navigator.clipboard.writeText(question);

            copiedQuestion.value = question;

            window.setTimeout(() => {
                if (copiedQuestion.value === question) {
                    copiedQuestion.value = null;
                }
            }, 1500);
        }
    } catch (err) {
        console.warn(
            "Unable to copy example question:",
            err,
        );
    }
}

function formatNumber(value) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
        return value ?? "—";
    }

    return new Intl.NumberFormat("en-US").format(number);
}

function normalizeRole(role) {
    if (!role) {
        return "Unknown";
    }

    return String(role)
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeType(type) {
    if (!type) {
        return "Unknown";
    }

    return String(type)
        .replace(/_/g, " ")
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

// Presentation only (Phase 4): same branching as before, restyled to
// design tokens. Status colors (warn/danger) are deliberately not used -
// a role is an identity, not a state - and the badge always shows the
// role's name, so meaning never rests on color alone.
function roleClass(role) {
    const normalized = String(role || "").toLowerCase();

    if (
        normalized.includes("metric") ||
        normalized.includes("numeric")
    ) {
        return "border-forest/20 bg-forest-soft text-forest";
    }

    if (
        normalized.includes("dimension") ||
        normalized.includes("categor")
    ) {
        return "border-line-strong bg-sunken text-ink";
    }

    if (
        normalized.includes("date") ||
        normalized.includes("time")
    ) {
        return "border-forest/30 bg-surface text-forest";
    }

    if (
        normalized.includes("identifier") ||
        normalized.includes("id")
    ) {
        return "border-line bg-surface text-ink-muted";
    }

    return "border-line bg-canvas text-ink-muted";
}

function clearSearch() {
    searchQuery.value = "";
}

// =========================================================
// SCHEMA PRESENTATION (visual reference)
// =========================================================

// The column shown in the details card: the user's pick, else the first
// measure, else the first column. Pure view state.
const selectedColumnName = ref("");

const selectedColumn = computed(() => {
    const byName = columns.value.find((column) => column.name === selectedColumnName.value);
    return byName || numericColumns.value[0] || columns.value[0] || null;
});

// Display names for the backend's roles, as in the reference.
const ROLE_LABELS = { metric: "Measure", numeric: "Measure", dimension: "Dimension", categorical: "Dimension", time: "Time", date: "Time", identifier: "Identifier" };

function roleLabel(role) {
    return ROLE_LABELS[String(role || "").toLowerCase()] || normalizeRole(role);
}

// A role is an identity, not a state: each gets its own hue, and the
// label is always shown, so meaning never rests on color alone.
const ROLE_STYLES = {
    Measure: { dot: "bg-[#b08a3e]", text: "text-[#8a6a2a]" },
    Dimension: { dot: "bg-[#3f8a4f]", text: "text-[#2f6b3c]" },
    Time: { dot: "bg-[#8fbf8a]", text: "text-[#4f7d4a]" },
    Identifier: { dot: "bg-[#d98a2b]", text: "text-[#b0661a]" },
};

function roleStyle(role) {
    return ROLE_STYLES[roleLabel(role)] || { dot: "bg-line-strong", text: "text-ink-muted" };
}

// Missing share of all rows, from the backend's own counts.
function missingPercent(column) {
    const missing = Number(column?.missing_count);
    const rows = Number(metadata.value?.row_count);
    if (!Number.isFinite(missing)) {
        return "—";
    }
    if (!Number.isFinite(rows) || rows <= 0) {
        return formatNumber(missing);
    }
    return `${((missing / rows) * 100).toFixed(1)}%`;
}

</script>

<template>
    <section aria-labelledby="schema-title" class="flex flex-col gap-5">

        <!-- Header -->
        <header class="flex flex-wrap items-start justify-between gap-3">
            <div>
                <h2 id="schema-title" class="text-[28px] font-bold leading-tight tracking-[-0.02em] text-ink">Dataset Schema</h2>
                <p class="mt-1 text-body text-ink-muted">Columns, data types and analytical roles.</p>
            </div>
            <div v-if="metadata" class="flex flex-wrap items-center gap-2">
                <div class="relative w-[240px] max-sm:w-full">
                    <Icon name="search" :size="16"
                        class="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-muted" />
                    <input v-model="searchQuery" type="search" placeholder="Filter columns…"
                        aria-label="Filter columns by name, role or type"
                        class="h-10 w-full appearance-none rounded-[10px] border border-[#e6decd] bg-surface pl-10 pr-9 text-data text-ink placeholder:text-ink-muted focus-visible:border-forest [&::-webkit-search-cancel-button]:hidden" />
                    <button v-if="searchQuery" type="button" aria-label="Clear filter"
                        class="absolute right-1.5 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-control text-ink-muted hover:bg-sunken hover:text-ink"
                        @click="clearSearch">
                        <Icon name="x" :size="14" />
                    </button>
                </div>
                <Button icon="refresh" :loading="refreshing" class="h-10 rounded-[10px] bg-surface px-4"
                    @click="loadMetadata({ refresh: true })">
                    {{ refreshing ? "Refreshing…" : "Refresh" }}
                </Button>
            </div>
        </header>

        <!-- Loading -->
        <div v-if="loading" class="rounded-[16px] border border-[#e6decd] bg-surface p-5" aria-busy="true"
            aria-label="Loading dataset schema">
            <div class="space-y-2">
                <div v-for="row in 8" :key="row" class="h-9 animate-pulse rounded-control bg-sunken"></div>
            </div>
        </div>

        <!-- Error -->
        <div v-else-if="error" role="alert"
            class="flex items-start gap-3 rounded-[14px] border border-danger/20 bg-danger-soft px-4 py-3 max-[600px]:flex-col">
            <Icon name="error" :size="16" class="mt-0.5 text-danger" />
            <div class="min-w-0 flex-1">
                <p class="text-data font-semibold text-danger">Unable to load dataset schema</p>
                <p class="mt-0.5 text-data text-ink">{{ error }}</p>
            </div>
            <Button size="sm" icon="refresh" @click="loadMetadata()">Try again</Button>
        </div>

        <template v-else-if="metadata">

            <div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">

                <!-- Columns table -->
                <div class="overflow-hidden rounded-[16px] border border-[#e6decd] bg-surface shadow-panel">
                    <div class="max-h-[620px] overflow-auto [scrollbar-width:thin]">
                        <table class="w-full min-w-[640px] border-separate border-spacing-0 text-left">
                            <caption class="sr-only">Dataset columns. Select a row to see its details.</caption>
                            <thead class="sticky top-0 z-10">
                                <tr class="text-data font-semibold text-ink">
                                    <th scope="col" class="w-12 border-b border-[#ece5d6] bg-[#f6f1e5] py-3 pl-5 pr-2">#</th>
                                    <th scope="col" class="border-b border-[#ece5d6] bg-[#f6f1e5] px-3 py-3">Column</th>
                                    <th scope="col" class="border-b border-[#ece5d6] bg-[#f6f1e5] px-3 py-3">Type</th>
                                    <th scope="col" class="border-b border-[#ece5d6] bg-[#f6f1e5] px-3 py-3">Role</th>
                                    <th scope="col" class="border-b border-[#ece5d6] bg-[#f6f1e5] px-3 py-3 text-right">Missing</th>
                                    <th scope="col" class="border-b border-[#ece5d6] bg-[#f6f1e5] py-3 pl-3 pr-5 text-right">Unique</th>
                                </tr>
                            </thead>
                            <tbody class="text-data text-ink">
                                <tr v-for="(column, index) in filteredColumns" :key="column.name"
                                    class="cursor-pointer transition-colors duration-150"
                                    :class="selectedColumn?.name === column.name ? 'bg-forest-soft/60' : 'hover:bg-canvas'"
                                    @click="selectedColumnName = column.name">
                                    <td class="border-b border-[#efe8da] py-3 pl-5 pr-2 tabular-nums text-ink-muted">{{ index + 1 }}</td>
                                    <th scope="row" class="max-w-[240px] border-b border-[#efe8da] px-3 py-3 font-normal">
                                        <button type="button" class="block max-w-full truncate text-left hover:underline"
                                            :aria-pressed="selectedColumn?.name === column.name" :title="column.name"
                                            @click.stop="selectedColumnName = column.name">
                                            {{ column.name }}
                                        </button>
                                    </th>
                                    <td class="whitespace-nowrap border-b border-[#efe8da] px-3 py-3 text-ink-muted">
                                        {{ column.data_type || "—" }}
                                    </td>
                                    <td class="whitespace-nowrap border-b border-[#efe8da] px-3 py-3">
                                        <span class="inline-flex items-center gap-1.5 font-medium" :class="roleStyle(column.role).text">
                                            <span aria-hidden="true" class="h-2 w-2 rounded-full" :class="roleStyle(column.role).dot"></span>
                                            {{ roleLabel(column.role) }}
                                        </span>
                                    </td>
                                    <td class="whitespace-nowrap border-b border-[#efe8da] px-3 py-3 text-right tabular-nums"
                                        :class="Number(column.missing_count) > 0 ? 'font-medium text-warn-ink' : ''">
                                        {{ missingPercent(column) }}
                                    </td>
                                    <td class="whitespace-nowrap border-b border-[#efe8da] py-3 pl-3 pr-5 text-right tabular-nums">
                                        {{ formatNumber(column.unique_values) }}
                                    </td>
                                </tr>
                            </tbody>
                        </table>

                        <EmptyState v-if="!filteredColumns.length && searchQuery" icon="search"
                            title="No columns match this filter"
                            :description="`Nothing matches “${searchQuery}”. Try a column name, role or type.`">
                            <template #action>
                                <Button size="sm" @click="clearSearch">Clear filter</Button>
                            </template>
                        </EmptyState>
                    </div>
                    <p class="border-t border-[#ece5d6] bg-[#f8f4ea] px-5 py-2.5 text-caption text-ink-muted">
                        <span class="tabular-nums">{{ visibleColumnCount }}</span> of
                        <span class="tabular-nums">{{ columnCount }}</span> columns
                    </p>
                </div>

                <!-- Column details -->
                <aside v-if="selectedColumn" aria-labelledby="column-detail-title"
                    class="rounded-[16px] border border-[#e6decd] bg-surface px-5 pb-5 pt-4 shadow-panel">
                    <h3 id="column-detail-title" class="truncate text-lead font-semibold text-ink" :title="selectedColumn.name">
                        Column: {{ selectedColumn.name }}
                    </h3>
                    <dl class="mt-3 divide-y divide-[#ece5d6] text-data">
                        <div class="flex items-center justify-between gap-3 py-2.5">
                            <dt class="text-ink-muted">Type</dt>
                            <dd class="rounded-[8px] bg-[#f0e9d9] px-2.5 py-1 font-medium text-ink">{{ selectedColumn.data_type || "—" }}</dd>
                        </div>
                        <div class="flex items-center justify-between gap-3 py-2.5">
                            <dt class="text-ink-muted">Role</dt>
                            <dd class="inline-flex items-center gap-1.5 rounded-[8px] bg-[#f0e9d9] px-2.5 py-1 font-medium"
                                :class="roleStyle(selectedColumn.role).text">
                                <span aria-hidden="true" class="h-2 w-2 rounded-full" :class="roleStyle(selectedColumn.role).dot"></span>
                                {{ roleLabel(selectedColumn.role) }}
                            </dd>
                        </div>
                        <div class="flex items-center justify-between gap-3 py-2.5">
                            <dt class="text-ink-muted">Missing</dt>
                            <dd class="tabular-nums text-ink">
                                {{ formatNumber(selectedColumn.missing_count ?? 0) }} ({{ missingPercent(selectedColumn) }})
                            </dd>
                        </div>
                        <div class="flex items-center justify-between gap-3 py-2.5">
                            <dt class="text-ink-muted">Unique</dt>
                            <dd class="font-semibold tabular-nums text-ink">{{ formatNumber(selectedColumn.unique_values) }}</dd>
                        </div>
                    </dl>

                    <div v-if="selectedColumn.allowed_operations?.length" class="mt-3">
                        <p class="text-data font-medium text-ink">Supported operations</p>
                        <p class="mt-1 text-data text-ink-muted">
                            {{ selectedColumn.allowed_operations.map((op) => String(op).replace(/_/g, " ")).join(", ") }}
                        </p>
                    </div>

                    <div v-if="Array.isArray(selectedColumn.sample_values) && selectedColumn.sample_values.length" class="mt-4">
                        <p class="text-data font-medium text-ink">Example values</p>
                        <p class="mt-1 break-words text-data text-ink-muted">
                            {{ [...new Set(selectedColumn.sample_values.map(String))].slice(0, 4).join(", ") }}
                        </p>
                    </div>
                </aside>
            </div>

            <!-- Example questions (unchanged behavior: runs in Analyze) -->
            <section v-if="exampleQuestions.length" aria-labelledby="schema-questions-title"
                class="rounded-[16px] border border-[#e6decd] bg-surface px-5 pb-5 pt-4 shadow-panel">
                <h3 id="schema-questions-title" class="text-lead font-semibold text-ink">Questions to ask</h3>
                <p class="mt-1 text-data text-ink-muted">
                    Pick one to run it in Analyze. It is also copied to your clipboard.
                </p>
                <div class="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                    <button v-for="(question, index) in exampleQuestions" :key="`${question}-${index}`" type="button"
                        class="group flex items-center gap-3 rounded-[10px] px-2 py-2 text-left transition-colors duration-150 hover:bg-sunken/60"
                        @click="selectQuestion(question)">
                        <span aria-hidden="true"
                            class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#f1ebdd] text-ink-muted group-hover:text-forest">
                            <Icon v-if="copiedQuestion !== question" name="arrow-right" :size="14" />
                            <Icon v-else name="check" :size="14" />
                        </span>
                        <span class="text-data text-ink">{{ question }}</span>
                        <span v-if="copiedQuestion === question" class="sr-only">Copied</span>
                    </button>
                </div>
            </section>

        </template>

        <!-- No dataset selected -->
        <div v-else class="rounded-[16px] border border-[#e6decd] bg-surface">
            <EmptyState icon="columns" title="No dataset selected"
                description="Upload or select a dataset to view its schema." />
        </div>

    </section>
</template>
