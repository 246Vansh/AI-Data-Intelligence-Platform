<script setup>
import { computed, defineAsyncComponent, h, onBeforeUnmount, ref, watch, nextTick } from "vue";

import AnalyticsInsights from "./AnalyticsInsights.vue";
import AnalyticsChartFallback from "./AnalyticsChartFallback.vue";

// Workspace Phase 0: the chart (and ECharts with it) is code-split and
// fetched on first use, so the initial page no longer downloads the
// charting library. Same component, same props - only how it loads.
const AnalyticsChart = defineAsyncComponent({
    loader: () => import("./AnalyticsChart.vue"),
    loadingComponent: { render: () => h(AnalyticsChartFallback, { state: "loading" }) },
    errorComponent: { render: () => h(AnalyticsChartFallback, { state: "error" }) },
    delay: 120,
});
import Button from "./ui/Button.vue";
import EmptyState from "./ui/EmptyState.vue";
import Icon from "./ui/Icon.vue";
import SegmentedControl from "./ui/SegmentedControl.vue";
import TabPanel from "./ui/TabPanel.vue";
import Tabs from "./ui/Tabs.vue";
import InspectorFrame from "./workspace/InspectorFrame.vue";
import Menu from "./ui/Menu.vue";
import Tooltip from "./ui/Tooltip.vue";

import { useBreakpoints } from "@vueuse/core";
import { AccordionContent, AccordionHeader, AccordionItem, AccordionRoot, AccordionTrigger } from "reka-ui";

import { useSuggestionMetadata } from "../composables/useSuggestionMetadata";
import { useUiPreference } from "../composables/useUiPreference";
import { formatCompactNumber, formatNumber, summarizeResult } from "../services/chartSummary";

import {
    analyzeDataset,
    getApiErrorMessage,
    isRequestCancelled,
} from "../services/api";
import {
    buildFollowUpContext,
    keepsPreviousAfterError,
    selectFollowUpContext,
} from "../services/followUpContext";

// =========================================================
// STATE
// =========================================================

const props = defineProps({
    incomingQuestion: {
        type: String,
        default: "",
    },
    datasetId: {
        type: String,
        default: "",
    },
    // Analysis Context (see composables/useAnalysisContext.js) - the
    // dataset store itself still lives in Dashboard.vue, these three
    // props are just its current selection resolved for this panel.
    analysisMode: {
        type: String,
        default: "single",
    },
    selectedDatasetIds: {
        type: Array,
        default: () => [],
    },
    selectedDatasetNames: {
        type: Array,
        default: () => [],
    },
});

const question = ref("");

const loading = ref(false);

const error = ref(null);
const errorStatus = ref(null);
const result = ref(null);

// Incremented on every analyze() call and whenever the question is
// replaced/cleared, so a response from a superseded request can never
// write into the current UI state. The superseded HTTP request is also
// aborted to free the browser connection; the server does not cancel
// work on disconnect, so an already-queued analysis may still run.
let analysisSeq = 0;
let analysisController = null;

function invalidateAnalysis() {
    analysisSeq += 1;
    loading.value = false;
    analysisController?.abort();
    analysisController = null;
    followUpPending.value = false;
}

onBeforeUnmount(invalidateAnalysis);

// Rendering every returned row (up to the backend's 10,000-row cap)
// would build a very large table DOM; the chart still uses all rows.
const MAX_TABLE_ROWS = 500;

const tableRows = computed(() =>
    (result.value?.data?.rows || []).slice(0, MAX_TABLE_ROWS),
);

// =========================================================
// FOLLOW-UP CONTEXT
//
// The canonical plan of the latest SUCCESSFUL analysis, sent back as
// analysis_context so a follow-up ("break that down by region") can be
// applied to it. Only that one plan - no rows, no transcript. Cleared on
// any failure, Clear, or new example, and never sent for another dataset
// (this component is also remounted whenever the selected dataset
// changes, which drops it entirely).
// =========================================================

const followUpContext = ref(null);
const followUpEnabled = ref(true);
const followUpPending = ref(false);

// True while the error shown is a rejected follow-up and the previous
// successful result below it is still the one being displayed.
const keptPreviousResult = ref(false);

const canFollowUp = computed(
    () => !!selectFollowUpContext(followUpContext.value, props.datasetId, true),
);

// Normalized view of result.plan_explanation; null when the backend
// sent none (older server, or explanation generation failed).
const planExplanation = computed(() => {
    const explanation = result.value?.plan_explanation;

    if (!explanation || !Array.isArray(explanation.steps) || !explanation.steps.length) {
        return null;
    }

    const labels = {
        "rule-based": "rule-based interpretation",
        ai: "AI interpretation",
        "follow-up": "follow-up to the previous result",
    };

    return {
        interpretedBy: labels[explanation.interpreted_by] || "interpretation",
        steps: explanation.steps.map(String),
        limitations: Array.isArray(explanation.limitations)
            ? explanation.limitations.map(String)
            : [],
    };
});

const tableRowsHidden = computed(
    () => (result.value?.data?.rows?.length ?? 0) > MAX_TABLE_ROWS,
);

// Classified from HTTP status only. 422 = the question couldn't be
// turned into a plan (clarification / rephrase). Retrying the same
// question can only help for network errors (no status) and 5xx other
// than 503 (503 = AI planner not configured, a permanent condition).
const isClarificationError = computed(() => errorStatus.value === 422);

const canRetry = computed(() => {
    const status = errorStatus.value;
    return !status || (status >= 500 && status !== 503);
});

const hasRows = computed(
    () => (result.value?.data?.rows?.length ?? 0) > 0,
);

// =========================================================
// DATASET METADATA
// =========================================================

const columns = computed(() => {
    const metadataColumns = metadata.value?.columns;

    if (!metadataColumns || typeof metadataColumns !== "object") {
        return {};
    }

    return metadataColumns;
});

const columnEntries = computed(() => {
    return Object.entries(columns.value);
});

const metricColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) => info?.role === "metric")
        .map(([name]) => name);
});

// A dimension is worth grouping by when the backend's own distinct
// count says it forms a handful of groups. An identifier-like column
// (one value per row, e.g. order_id) would produce one "group" per row,
// so it is never suggested. Columns without a reported count keep
// their place after the groupable ones.
const MAX_SUGGESTED_GROUPS = 50;

function groupability(info) {
    const unique = Number(info?.unique_values);
    const rowCount = Number(metadata.value?.row_count);
    if (!Number.isFinite(unique)) {
        return 1; // unknown
    }
    if (unique < 2 || unique > MAX_SUGGESTED_GROUPS || (Number.isFinite(rowCount) && unique >= rowCount)) {
        return 2; // not useful as a grouping
    }
    return 0; // groupable
}

const dimensionColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) =>
            ["dimension", "categorical"].includes(info?.role) && groupability(info) < 2,
        )
        .sort(([, a], [, b]) => groupability(a) - groupability(b))
        .map(([name]) => name);
});

const timeColumns = computed(() => {
    return columnEntries.value
        .filter(([, info]) => info?.role === "time")
        .map(([name]) => name);
});

// =========================================================
// EXAMPLE QUESTION GENERATION
// =========================================================
//
// SINGLE mode keeps the existing dataset-driven example generation
// below. COMPARISON / CROSS_DATASET use static suggestion templates
// instead - there's no per-dataset column context to build them
// from yet, and no cross-dataset reasoning implemented at this
// stage (see plan_executor.py / ai/planner.py - unchanged).

const COMPARISON_SUGGESTIONS = [
    "Compare the selected datasets.",
    "What changed between these datasets?",
    "Which dataset performed better?",
    "Compare trends.",
    "Which categories increased or decreased?",
];

const CROSS_DATASET_SUGGESTIONS = [
    "What relationships exist between these datasets?",
    "Which entities appear across the selected datasets?",
    "What combined insights can be found?",
];

// Each suggestion: a short chip label (as in the visual reference) and
// the full question it fills in - the same questions as before, so
// nothing new is sent to the planner. `trend` marks time-based ones.
function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

const exampleQuestions = computed(() => {
    if (props.analysisMode === "comparison") {
        return COMPARISON_SUGGESTIONS.map((question) => ({ label: question, question }));
    }

    if (props.analysisMode === "cross_dataset") {
        return CROSS_DATASET_SUGGESTIONS.map((question) => ({ label: question, question }));
    }

    const examples = [];

    const metric = metricColumns.value[0];
    const secondMetric = metricColumns.value[1];

    const dimension = dimensionColumns.value[0];
    const secondDimension = dimensionColumns.value[1];

    const timeColumn = timeColumns.value[0];

    // Time-based examples
    if (timeColumn && metric) {
        examples.push({ label: `Monthly ${metric} trend`, question: `Show me the monthly trend of ${metric}.`, trend: true });
    }

    // Dimension + metric examples
    if (dimension && metric) {
        examples.push({ label: `${capitalize(metric)} by ${dimension}`, question: `Show the top 5 ${dimension} by total ${metric}.` });
        examples.push({ label: `Average ${metric} by ${dimension}`, question: `Show the average ${metric} by ${dimension}.` });
    }

    // Second dimension
    if (secondDimension && metric && secondDimension !== dimension) {
        examples.push({ label: `Top performing ${secondDimension}`, question: `Show the top 5 ${secondDimension} by average ${metric}.` });
    }

    if (timeColumn && metric) {
        examples.push({ label: `Yearly ${metric} trend`, question: `Show me the yearly trend of ${metric}.`, trend: true });
    }

    // Second metric
    if (secondMetric && dimension && secondMetric !== metric) {
        examples.push({ label: `Average ${secondMetric} by ${dimension}`, question: `Show the average ${secondMetric} by ${dimension}.` });
    }

    // Fallback
    if (!examples.length && metric) {
        examples.push({ label: `Total ${metric}`, question: `Show the total ${metric}.` });
        examples.push({ label: `Average ${metric}`, question: `Show the average ${metric}.` });
    }

    if (!examples.length && dimension) {
        examples.push({ label: `${capitalize(dimension)} distribution`, question: `Show the distribution of ${dimension}.` });
    }

    const seen = new Set();
    return examples.filter((example) => !seen.has(example.question) && seen.add(example.question)).slice(0, 4);
});

// =========================================================
// CELL FORMATTING
// =========================================================

function formatCell(value) {
    if (value === null || value === undefined) {
        return "—";
    }

    if (typeof value === "number") {
        if (Number.isInteger(value)) {
            return value.toLocaleString("en-US");
        }

        return value.toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
    }

    return value;
}

// =========================================================
// SUGGESTION METADATA (on demand)
// =========================================================
//
// /metadata feeds only the suggestion chips and "next question" ideas.
// It is requested ONLY by the "Suggest questions" button - never on
// selection, focus or submit, because its first build holds the
// dataset's locks on the server and would delay the user's question.
// A copy already cached by the Data or Schema tab is reused with no
// request. See useSuggestionMetadata.

const {
    data: metadata,
    loading: metadataLoading,
    error: metadataError,
    showSuggestButton,
    requestSuggestions,
} = useSuggestionMetadata({
    datasetId: () => props.datasetId,
    analysisMode: () => props.analysisMode,
});

// =========================================================
// ANALYZE
// =========================================================

async function analyze() {
    const trimmedQuestion = question.value.trim();

    if (!trimmedQuestion || loading.value || !props.datasetId) {
        return;
    }

    const seq = ++analysisSeq;
    analysisController?.abort();
    const controller = new AbortController();
    analysisController = controller;

    // Captured so a response that resolves after the user has
    // already switched datasets can be detected and ignored below,
    // instead of overwriting the result for the newly selected
    // dataset with an answer computed against the old one.
    const requestedDatasetId = props.datasetId;

    // Fixed before the request is sent, so toggling the checkbox while it
    // runs cannot change how its failure is handled.
    let submittedAsFollowUp = false;

    try {
        // The current result stays visible until this request succeeds
        // (replaced) or fails (cleared - except a rejected follow-up), so
        // the follow-up context always matches the result on screen.
        loading.value = true;
        error.value = null;
        errorStatus.value = null;
        keptPreviousResult.value = false;

        const analysisContext = selectFollowUpContext(
            followUpContext.value,
            requestedDatasetId,
            followUpEnabled.value,
        );

        submittedAsFollowUp = !!analysisContext;
        followUpPending.value = submittedAsFollowUp;

        const response =
            await analyzeDataset(trimmedQuestion, requestedDatasetId, analysisContext, {
                signal: controller.signal,
            });

        if (seq !== analysisSeq || requestedDatasetId !== props.datasetId) {
            return;
        }

        if (!response?.success) {
            const responseError = response?.error;

            error.value =
                responseError?.message ||
                (typeof responseError === "string" ? responseError : null) ||
                "Unable to analyze the dataset.";

            result.value = null;
            followUpContext.value = null;
            return;
        }

        result.value = response;
        followUpContext.value = buildFollowUpContext(response, requestedDatasetId);
        followUpEnabled.value = true;
    } catch (err) {
        if (
            seq !== analysisSeq ||
            requestedDatasetId !== props.datasetId ||
            isRequestCancelled(err)
        ) {
            return;
        }

        console.error(
            "Analysis request failed:",
            err,
        );

        errorStatus.value = err?.response?.status ?? null;

        error.value =
            getApiErrorMessage(err) ||
            "Unable to analyze dataset.";

        // A failed analysis never becomes the next follow-up's context. A
        // rejected follow-up (422) leaves the previous successful result
        // and its context untouched - never restores anything - so the
        // user can rephrase; reached only for the current, non-cancelled
        // request on the same dataset (guards above).
        if (keepsPreviousAfterError(submittedAsFollowUp, errorStatus.value)) {
            keptPreviousResult.value = !!result.value;
        } else {
            result.value = null;
            followUpContext.value = null;
        }
    } finally {
        if (analysisController === controller) {
            analysisController = null;
        }

        if (seq === analysisSeq && requestedDatasetId === props.datasetId) {
            loading.value = false;
            followUpPending.value = false;
        }
    }
}

// =========================================================
// EXAMPLES
// =========================================================

function useExample(example) {
    if (loading.value) {
        return;
    }

    question.value = example;
    error.value = null;
    errorStatus.value = null;
    result.value = null;
    followUpContext.value = null;
}

function clearAnalysis() {
    invalidateAnalysis();
    question.value = "";
    error.value = null;
    errorStatus.value = null;
    result.value = null;
    followUpContext.value = null;
}

function handleKeydown(event) {
    if (
        event.ctrlKey &&
        event.key === "Enter"
    ) {
        event.preventDefault();
        analyze();
    }
}


watch(
    () => props.incomingQuestion,
    async (newQuestion) => {
        if (!newQuestion) {
            return;
        }

        question.value = newQuestion;

        // Clear previous analysis when a new example is selected, and
        // drop any still-running request for the previous question.
        invalidateAnalysis();
        error.value = null;
        errorStatus.value = null;
        result.value = null;
        followUpContext.value = null;

        await nextTick();
    },
    {
        immediate: true,
    },
);

// =========================================================
// WORKSPACE PRESENTATION (Phase 2)
// =========================================================
//
// View-only state for the Analyze workspace. Nothing below reads or
// writes the analysis, follow-up, cancellation or error state above -
// it only decides how the current result is laid out.
//
// - The inspector (findings + calculation) docks on the right from
//   1024px, below that it stacks under the result; its open/closed
//   choice is a UI preference.
// - Chart | Table: the chart is offered exactly when it was before
//   (rows + a non-table visualization); the table shows the same
//   returned rows (tableRows, 500-row cap) that table results always
//   showed. A table-type result opens on Table, as before.
// - On mobile the composer folds into a one-line question bar once a
//   result exists; tapping it expands the composer again.
// - The KPI row uses services/chartSummary.js, the same implementation
//   the chart uses, so the figures can never disagree.

const breakpoints = useBreakpoints({ tablet: 768, desktop: 1024 });
const isMobile = breakpoints.smaller("tablet");
const inspectorDocked = breakpoints.greaterOrEqual("desktop");
const inspectorOpen = useUiPreference("analyze.inspector-open", true);

const questionInput = ref(null);
const composerExpanded = ref(false);
const resultView = ref("chart");

const summary = computed(() => (result.value ? summarizeResult(result.value) : null));

// Same condition that has always decided whether the chart renders.
const canShowChart = computed(
    () => hasRows.value && !!result.value?.visualization && result.value.visualization.type !== "table",
);

// Same condition that has always decided whether the results table renders.
const isTableResult = computed(
    () => result.value?.visualization?.type === "table" || (!!result.value?.visualization && !hasRows.value),
);

const RESULT_VIEWS = [
    { value: "chart", label: "Chart", icon: "bar-chart" },
    { value: "table", label: "Table", icon: "table" },
];

const insightCount = computed(() => result.value?.insights?.insights?.length || 0);

const showCompactQuestion = computed(
    () => isMobile.value && !!result.value && !composerExpanded.value && !loading.value,
);

// A new result opens on its natural view and folds the mobile composer.
watch(result, (next, previous) => {
    if (next && next !== previous) {
        resultView.value = canShowChart.value ? "chart" : "table";
        composerExpanded.value = false;
    }
});

function expandComposer() {
    composerExpanded.value = true;
    nextTick(() => questionInput.value?.focus());
}

// =========================================================
// ANALYZE WORKSPACE PRESENTATION (visual redesign, Stage 2)
// =========================================================
//
// Still view-only: everything below reads the state above and never
// changes how a question is planned, executed or followed up.

// The follow-up switch, shown as "Follow up | New question". Same
// boolean (followUpEnabled) the checkbox used to bind.
const COMPOSER_MODES = [
    { value: "follow-up", label: "Follow up", icon: "message" },
    { value: "new", label: "New question", icon: "plus" },
];

const composerMode = computed({
    get: () => (followUpEnabled.value ? "follow-up" : "new"),
    set: (value) => {
        if (!loading.value) {
            followUpEnabled.value = value === "follow-up";
        }
    },
});

// Refinements offered after a result. Only edits the existing
// follow-up resolver (ai/follow_up.py) applies to the previous plan:
// flipping a top/bottom N ranking, or replacing a single grouping
// column with another real dimension of this dataset. Choosing one
// only fills the composer (in follow-up mode) - nothing is sent until
// the user presses Analyze.
const refineSuggestions = computed(() => {
    if (!canFollowUp.value || props.analysisMode !== "single") {
        return [];
    }

    const plan = result.value?.plan || {};
    const grouped = Array.isArray(plan.group_by) ? plan.group_by : [];
    const suggestions = [];

    if (grouped.length && Number.isInteger(plan.limit) && plan.limit > 0) {
        suggestions.push(plan.sort === "asc"
            ? `Make it the top ${plan.limit} instead`
            : `Make it the bottom ${plan.limit} instead`);
    }

    if (grouped.length === 1 && !plan.time_granularity) {
        for (const dimension of dimensionColumns.value) {
            if (!grouped.includes(dimension) && suggestions.length < 3) {
                suggestions.push(`Show it by ${dimension} instead`);
            }
        }
    }

    return suggestions;
});

function applyRefinement(text) {
    if (loading.value) {
        return;
    }
    question.value = text;
    followUpEnabled.value = true;
    composerExpanded.value = true;
    nextTick(() => questionInput.value?.focus());
}

// Who planned the analysis (backend's own label), shown on the result.
const SOURCE_LABELS = { "rule-based": "Rule-based analysis", ai: "AI-planned analysis", "follow-up": "Follow-up" };
const resultSource = computed(() => SOURCE_LABELS[result.value?.plan_explanation?.interpreted_by] || "");

const returnedRowCount = computed(() => result.value?.data?.row_count ?? result.value?.data?.rows?.length ?? 0);

// The group a KPI extreme belongs to, read from the same rows/values
// the chart uses. Only named when exactly one group holds the value.
function groupFor(value) {
    const current = summary.value;
    if (!current || value === null || value === undefined) {
        return "";
    }
    const matches = current.numericValues
        .map((number, index) => (number === value ? index : -1))
        .filter((index) => index >= 0);
    if (matches.length !== 1) {
        return "";
    }
    const label = current.rows[matches[0]]?.[current.xColumn];
    return label === null || label === undefined || label === "" ? "Unknown" : String(label);
}

// Chart view on a wide canvas: the plotted values beside the chart,
// when there are few enough groups to read at a glance.
const SIDE_TABLE_MAX_ROWS = 12;
const showSideTable = computed(
    () => !!summary.value?.hasChartData && summary.value.rows.length <= SIDE_TABLE_MAX_ROWS,
);

const inspectorTab = ref("findings");
const INSPECTOR_TABS = computed(() => [
    { value: "findings", label: "Findings" },
    ...(planExplanation.value ? [{ value: "calculation", label: "Calculation" }] : []),
]);

// ---- Result header -------------------------------------------------

// One line describing the result: the executed plan's first step
// ("Sum of revenue for each region."), else the question asked.
const resultDescription = computed(
    () => planExplanation.value?.steps?.[0] || result.value?.question || "",
);

const rowInfo = computed(() => {
    const data = result.value?.data;
    if (!data) {
        return "";
    }
    return data.row_limit_reached
        ? `Row limit of ${formatNumber(data.row_limit)} reached - any groups beyond it are not shown, and insights only state what the returned rows can support.`
        : `${formatNumber(returnedRowCount.value)} rows returned by this analysis.`;
});

// ---- KPI tiles (values from services/chartSummary.js) -------------

const metricName = computed(() => result.value?.plan?.metric || summary.value?.yColumn || "value");

const kpiTiles = computed(() => {
    const current = summary.value;
    if (!current?.showKpis) {
        return [];
    }
    const x = current.xColumn || "group";
    return [
        current.totalLabel
            ? {
                key: "total",
                label: `Total ${metricName.value}${current.rowLimitReached ? " (shown)" : ""}`,
                value: current.totalValue,
                icon: "layers",
                tile: "bg-[#f3e9d3] text-[#9a7634]",
            }
            : {
                key: "groups",
                label: `${capitalize(x)} groups`,
                value: current.rows.length,
                icon: "layers",
                tile: "bg-[#f3e9d3] text-[#9a7634]",
            },
        { key: "average", label: `Avg. per ${x}`, value: current.averageValue, icon: "trend-up", tile: "bg-[#e6eee1] text-forest" },
        { key: "highest", label: "Highest", value: current.maximumValue, sub: groupFor(current.maximumValue), icon: "arrow-up", tile: "bg-[#e1f0dc] text-[#24803a]" },
        { key: "lowest", label: "Lowest", value: current.minimumValue, sub: groupFor(current.minimumValue), icon: "arrow-down", tile: "bg-[#fbe4df] text-[#d1352b]" },
    ];
});

// ---- Plotted-values table beside the chart ------------------------

// Share of the shown total - only meaningful for additive aggregations
// (sum / count), where the group values add up to a total.
const showShare = computed(() => !!summary.value?.totalLabel && summary.value.totalValue > 0);

function shareFor(row) {
    const value = Number(row?.[summary.value?.yColumn]);
    if (!showShare.value || !Number.isFinite(value)) {
        return "—";
    }
    return `${((value / summary.value.totalValue) * 100).toFixed(1)}%`;
}

// ---- Next questions -------------------------------------------------
//
// Follow-ups the resolver supports for this result first, then other
// suggestions built from this dataset's columns. Nothing is invented.

const nextQuestions = computed(() => {
    if (!result.value) {
        return [];
    }
    const items = refineSuggestions.value.map((text) => ({ key: `r-${text}`, label: text, refine: true }));
    for (const example of exampleQuestions.value) {
        if (example.question !== result.value.question) {
            items.push({ key: `e-${example.question}`, label: example.question, example });
        }
    }
    return items.slice(0, 3);
});

function chooseNextQuestion(item) {
    if (item.refine) {
        applyRefinement(item.label);
    } else {
        useExample(item.example.question);
        nextTick(() => questionInput.value?.focus());
    }
}

// The composer's "Refine" menu: the same supported follow-ups.
const refineMenuItems = computed(() =>
    refineSuggestions.value.map((text) => ({ key: text, label: text, icon: "arrow-right" })),
);

// ---- Mobile: "View findings" ---------------------------------------

const stackedSections = ref(["findings"]);

function viewFindings() {
    if (!stackedSections.value.includes("findings")) {
        stackedSections.value = [...stackedSections.value, "findings"];
    }
    nextTick(() => document.getElementById("analyze-findings")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}
// A result without an explanation has no Calculation tab to stay on.
watch(planExplanation, (explanation) => {
    if (!explanation && inspectorTab.value === "calculation") {
        inspectorTab.value = "findings";
    }
});

</script>

<template>
    <section class="flex min-h-0 flex-col" :class="isMobile ? '' : 'h-full'">

        <InspectorFrame storage-key="workspace-analyze-inspector-v2" inspector-label="Findings and calculation"
            :stacked="!inspectorDocked" :collapsed="!inspectorOpen" bare :default-size="300">

            <!-- =====================================================
                 ANALYTICAL CANVAS
            ====================================================== -->

            <div class="mx-auto flex w-full max-w-[1100px] flex-col px-4 pb-6 pt-5 sm:px-6 lg:pl-9 lg:pr-5 lg:pt-7"
                :class="isMobile ? 'gap-4' : 'min-h-full gap-5'">

                <!-- Heading -->
                <header>
                    <h2 v-if="!isMobile" class="text-[34px] font-bold leading-[1.15] tracking-[-0.025em] text-ink">
                        Analyze your data
                        <span class="font-serif text-[38px] font-normal italic tracking-[-0.01em] text-forest">with AI</span>
                    </h2>
                    <h2 v-else class="text-[26px] font-bold leading-tight tracking-[-0.02em] text-ink">Ask your data</h2>
                    <p class="mt-1.5 text-ink-muted" :class="isMobile ? 'text-data' : 'text-body'">
                        {{ isMobile
                            ? "Get insights, charts and exact calculations."
                            : "Ask a question in natural language and get insights, charts and exact calculations." }}
                    </p>
                </header>

                <!-- Notices -->

                <p v-if="metadataLoading" role="status" class="flex items-center gap-2.5 text-data text-ink-muted">
                    <span aria-hidden="true"
                        class="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-forest/30 border-t-forest"></span>
                    Understanding your dataset…
                </p>

                <p v-if="metadataError" role="alert"
                    class="flex items-center gap-2.5 rounded-control border border-warn-ink/15 bg-warn-soft px-3.5 py-2 text-data text-warn-ink">
                    <Icon name="warning" :size="16" />
                    {{ metadataError }}
                </p>

                <!-- =================================================
                     COMPOSER
                ================================================== -->

                <!-- Mobile, after a result: a one-line question bar -->
                <button v-if="showCompactQuestion" type="button" :aria-expanded="false"
                    class="flex h-[52px] w-full items-center gap-3 rounded-[14px] border border-line bg-surface px-4 text-left shadow-panel"
                    @click="expandComposer">
                    <span class="min-w-0 flex-1 truncate text-body text-ink">{{ result?.question || question }}</span>
                    <span class="shrink-0 text-caption font-semibold text-forest">Ask again</span>
                </button>

                <!-- Mobile composer: one line, mic (planned) or send -->
                <div v-else-if="isMobile"
                    class="rounded-[14px] border border-line bg-surface shadow-[0_1px_2px_rgb(24_61_48/0.05),0_4px_12px_-6px_rgb(24_61_48/0.12)] focus-within:border-forest/60 focus-within:ring-4 focus-within:ring-forest/10">
                    <div class="flex items-center gap-2 pl-4 pr-1.5">
                        <label for="question" class="sr-only">Ask your data</label>
                        <textarea id="question" ref="questionInput" v-model="question" rows="1"
                            :disabled="loading || !datasetId"
                            :placeholder="!datasetId ? 'Choose a dataset first' : (canFollowUp && followUpEnabled ? 'Refine the result…' : 'What do you want to know?')"
                            @keydown="handleKeydown"
                            class="block min-h-[50px] flex-1 resize-none bg-transparent py-3.5 text-body text-ink outline-none placeholder:text-ink-muted focus-visible:outline-none"></textarea>
                        <button v-if="(question || result) && !loading" type="button" aria-label="Clear question and result"
                            class="grid h-10 w-10 shrink-0 place-items-center rounded-full text-ink-muted hover:bg-sunken hover:text-ink"
                            @click="clearAnalysis">
                            <Icon name="x" :size="16" />
                        </button>
                        <button v-if="question.trim() || loading" type="button" aria-label="Analyze"
                            :disabled="!question.trim() || !datasetId || loading"
                            class="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-[#183427] text-on-forest disabled:opacity-60"
                            @click="analyze">
                            <span v-if="loading" aria-hidden="true"
                                class="h-4 w-4 animate-spin rounded-full border-2 border-on-forest/30 border-t-on-forest"></span>
                            <Icon v-else name="send" :size="16" />
                        </button>
                        <Tooltip v-else content="Voice input - coming soon">
                            <button type="button" aria-label="Voice input (coming soon)" aria-disabled="true"
                                class="grid h-10 w-10 shrink-0 cursor-default place-items-center rounded-full text-ink">
                                <Icon name="mic" :size="20" />
                            </button>
                        </Tooltip>
                    </div>
                    <div v-if="canFollowUp" class="flex items-center gap-2 border-t border-line/70 px-2 py-1.5">
                        <SegmentedControl v-model="composerMode" :items="COMPOSER_MODES" label="Question mode" size="sm" />
                    </div>
                </div>

                <!-- Desktop composer -->
                <div v-else
                    class="shrink-0 overflow-hidden rounded-[16px] border border-[#e6decd] bg-surface shadow-[0_1px_2px_rgb(24_61_48/0.04),0_8px_24px_-12px_rgb(24_61_48/0.16)] transition-[border-color,box-shadow] duration-150 focus-within:border-forest/50 focus-within:ring-4 focus-within:ring-forest/10"
                    :class="!datasetId ? 'opacity-70' : ''">

                    <div class="flex items-start gap-3 px-5 pb-3 pt-4">
                        <span aria-hidden="true"
                            class="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[#f0eadc] text-forest">
                            <Icon name="sparkle" :size="16" />
                        </span>
                        <div class="min-w-0 flex-1">
                            <label for="question" class="sr-only">Ask your data</label>
                            <p v-if="canFollowUp && followUpEnabled"
                                class="mb-0.5 flex min-w-0 items-center gap-1.5 text-caption text-forest">
                                <Icon name="message" :size="14" />
                                <span class="truncate">Following up on “{{ result?.question }}”</span>
                            </p>
                            <textarea id="question" ref="questionInput" v-model="question" rows="1"
                                :disabled="loading || !datasetId"
                                :placeholder="!datasetId
                                    ? 'Choose a dataset to start asking questions'
                                    : canFollowUp && followUpEnabled
                                        ? 'Refine the result, e.g. “only include the North region” or “by city instead”'
                                        : 'What would you like to know about your data?'"
                                @keydown="handleKeydown"
                                class="block min-h-9 w-full resize-none bg-transparent py-1.5 text-[17px] leading-snug text-ink outline-none [field-sizing:content] placeholder:text-ink-muted focus-visible:outline-none disabled:cursor-not-allowed">
                            </textarea>
                        </div>
                        <Tooltip v-if="question || result" content="Clear">
                            <button type="button" aria-label="Clear question and result" :disabled="loading"
                                class="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full text-ink-muted transition-colors duration-150 hover:bg-sunken hover:text-ink disabled:opacity-50"
                                @click="clearAnalysis">
                                <Icon name="x" :size="16" />
                            </button>
                        </Tooltip>
                    </div>

                    <div class="flex items-center gap-2 border-t border-[#efe8da] bg-[#f8f4ea] px-4 py-2.5">

                        <!-- Follow up: continue from the current result (same
                             switch as before); only possible after a result. -->
                        <Tooltip :content="canFollowUp ? (followUpEnabled ? 'Following up on this result - press to ask a new question instead' : 'Follow up on this result') : 'Available after an analysis'">
                            <button type="button" :aria-pressed="canFollowUp && followUpEnabled"
                                :aria-disabled="!canFollowUp || loading"
                                class="flex h-9 items-center gap-2 rounded-[10px] border px-3.5 text-body font-medium transition-colors duration-150"
                                :class="canFollowUp && followUpEnabled
                                    ? 'border-forest/25 bg-forest-soft text-forest'
                                    : 'border-transparent bg-surface text-ink hover:border-line'"
                                @click="canFollowUp && !loading && (composerMode = followUpEnabled ? 'new' : 'follow-up')">
                                <Icon name="plus" :size="16" />
                                Follow up
                            </button>
                        </Tooltip>

                        <!-- Refine: supported follow-up edits for this result -->
                        <Menu v-if="refineMenuItems.length" :items="refineMenuItems" align="start"
                            @select="applyRefinement">
                            <template #trigger>
                                <button type="button" :disabled="loading"
                                    class="flex h-9 items-center gap-2 rounded-[10px] border border-transparent bg-surface px-3.5 text-body font-medium text-ink transition-colors duration-150 hover:border-line data-[state=open]:border-line">
                                    <Icon name="sliders" :size="16" />
                                    Refine
                                </button>
                            </template>
                        </Menu>
                        <Tooltip v-else content="Available after an analysis">
                            <button type="button" aria-disabled="true"
                                class="flex h-9 cursor-default items-center gap-2 rounded-[10px] border border-transparent bg-surface px-3.5 text-body font-medium text-ink">
                                <Icon name="sliders" :size="16" />
                                Refine
                            </button>
                        </Tooltip>

                        <button type="button" :aria-label="loading ? 'Analyzing…' : (canFollowUp && followUpEnabled ? 'Refine result' : 'Analyze')"
                            :aria-busy="loading ? 'true' : undefined" :disabled="loading || !question.trim() || !datasetId"
                            class="ml-auto grid h-10 w-11 place-items-center rounded-[10px] bg-[#173326] text-on-forest shadow-[0_1px_2px_rgb(0_0_0/0.2)] transition-colors duration-150 hover:bg-forest disabled:cursor-not-allowed disabled:bg-[#173326]/55"
                            @click="analyze">
                            <span v-if="loading" aria-hidden="true"
                                class="h-4 w-4 animate-spin rounded-full border-2 border-on-forest/30 border-t-on-forest"></span>
                            <Icon v-else name="send" :size="16" />
                        </button>
                    </div>

                </div>

                <!-- Suggestions (real columns; the chip shows a short label,
                     the full question is what gets filled in) -->

                <button v-if="showSuggestButton" type="button" :disabled="loading" @click="requestSuggestions"
                    class="flex h-9 w-fit shrink-0 items-center gap-1.5 rounded-full border border-dashed border-[#e3dbca] bg-surface px-4 text-data font-medium text-ink transition-colors duration-150 hover:border-forest/35 hover:bg-forest-soft disabled:opacity-50">
                    <Icon name="sparkle" :size="14" class="text-forest" />
                    Suggest questions
                </button>

                <div v-if="datasetId && exampleQuestions.length"
                    class="-mx-4 flex items-center gap-2.5 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:flex-wrap sm:px-0">
                    <span v-if="!isMobile" class="mr-1.5 shrink-0 text-body font-medium text-ink">Try asking</span>
                    <Tooltip v-for="example in exampleQuestions" :key="example.question" :content="example.question">
                        <button type="button" :disabled="loading" @click="useExample(example.question)"
                            class="flex h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border bg-surface px-4 text-data font-medium text-ink transition-colors duration-150 hover:bg-forest-soft disabled:opacity-50"
                            :class="isMobile ? 'border-forest/45' : 'border-[#e3dbca] hover:border-forest/35'">
                            <span v-if="example.trend && !isMobile" aria-hidden="true"
                                class="grid h-3.5 w-3.5 place-items-center rounded-full bg-[#4f8a57]">
                                <span class="h-1.5 w-1.5 rounded-full bg-[#d8ecd3]"></span>
                            </span>
                            {{ example.label }}
                        </button>
                    </Tooltip>
                </div>

                <!-- Running status (the previous result stays visible
                     below - dimmed - until replaced) -->

                <p v-if="loading && result" role="status" class="flex items-center gap-2.5 text-data text-ink">
                    <span aria-hidden="true"
                        class="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-forest/20 border-t-forest"></span>
                    <span class="font-medium">{{ followUpPending ? "Applying your follow-up" : "Analyzing your question" }}</span>
                    <span class="text-ink-muted max-sm:hidden">Planning the analysis and preparing your results…</span>
                </p>

                <!-- Error: 422 = couldn't be planned (rephrase); else failure -->

                <div v-if="error" role="alert" class="flex items-start gap-3 rounded-[14px] border px-4 py-3.5"
                    :class="isClarificationError ? 'border-warn-ink/20 bg-warn-soft' : 'border-danger/20 bg-danger-soft'">
                    <Icon :name="isClarificationError ? 'info' : 'error'" :size="16" class="mt-0.5"
                        :class="isClarificationError ? 'text-warn-ink' : 'text-danger'" />
                    <div class="min-w-0">
                        <p class="text-data font-semibold" :class="isClarificationError ? 'text-warn-ink' : 'text-danger'">
                            {{ isClarificationError ? "Couldn't answer that question" : "Analysis failed" }}
                        </p>
                        <p class="mt-0.5 break-words text-data text-ink">{{ error }}</p>
                        <p v-if="keptPreviousResult && result" class="mt-1 text-caption font-medium text-warn-ink">
                            The previous result below is unchanged - edit your follow-up and try again.
                        </p>
                        <p v-if="isClarificationError" class="mt-1 text-caption text-ink-muted">
                            Try rephrasing with specific column names, e.g. which metric to measure and what to group it by.
                        </p>
                        <Button v-if="canRetry" size="sm" icon="refresh" class="mt-2.5"
                            :disabled="loading || !question.trim()" @click="analyze">
                            Try again
                        </Button>
                    </div>
                </div>

                <!-- No dataset: the shell's empty state goes here -->

                <slot v-if="!datasetId" name="empty" />

                <!-- First run: loading frame, or where the answer lands -->

                <div v-else-if="!result && loading" role="status"
                    class="flex min-h-[320px] flex-1 flex-col rounded-[16px] border border-[#e6decd] bg-surface shadow-panel">
                    <div class="flex items-center gap-3 px-5 py-4">
                        <span aria-hidden="true"
                            class="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-forest/20 border-t-forest"></span>
                        <div>
                            <p class="text-body font-semibold text-ink">
                                {{ followUpPending ? "Applying your follow-up" : "Analyzing your question" }}
                            </p>
                            <p class="text-caption text-ink-muted">Planning the analysis and preparing your results…</p>
                        </div>
                    </div>
                    <div aria-hidden="true" class="flex flex-1 items-end gap-[5%] px-8 pb-8 pt-6">
                        <span v-for="height in [176, 132, 108, 80, 60]" :key="height"
                            class="flex-1 animate-pulse rounded-t-md bg-sunken" :style="{ height: `${height}px` }"></span>
                    </div>
                </div>

                <div v-else-if="!result && !error"
                    class="flex min-h-[220px] flex-1 flex-col items-center justify-center gap-4 rounded-[16px] border border-dashed border-line-strong px-6 py-10 text-center">
                    <div aria-hidden="true" class="flex h-14 items-end gap-1.5">
                        <span v-for="(height, index) in [100, 74, 58, 40, 30]" :key="height" class="w-3 rounded-t-[3px]"
                            :class="['bg-rank-1', 'bg-rank-2', 'bg-rank-3', 'bg-rank-4', 'bg-rank-5'][index]"
                            :style="{ height: `${height}%`, opacity: 0.35 }"></span>
                    </div>
                    <div>
                        <p class="text-body font-semibold text-ink">Your answer appears here</p>
                        <p class="mt-1 max-w-[46ch] text-data text-ink-muted">
                            Ask a question above, or start from one of the suggestions built from this dataset's columns.
                        </p>
                    </div>
                </div>

                <!-- =================================================
                     RESULT
                ================================================== -->

                <Transition enter-active-class="transition duration-300 ease-out-quiet"
                    enter-from-class="translate-y-1 opacity-0" enter-to-class="translate-y-0 opacity-100">

                    <section v-if="result"
                        class="@container flex min-h-0 flex-col rounded-[16px] border border-[#e6decd] bg-surface shadow-[0_1px_2px_rgb(24_61_48/0.04),0_10px_30px_-18px_rgb(24_61_48/0.2)] transition-opacity duration-150"
                        :class="[loading ? 'opacity-60' : '']" :aria-busy="loading ? 'true' : 'false'"
                        aria-labelledby="analysis-result-title">

                        <!-- Header -->

                        <header class="flex flex-wrap items-start gap-x-4 gap-y-3 px-4 pt-4 sm:px-6 sm:pt-5">

                            <span aria-hidden="true"
                                class="grid shrink-0 place-items-center rounded-[10px] bg-[#e4eedd] text-forest"
                                :class="isMobile ? 'h-9 w-9' : 'h-11 w-11'">
                                <Icon name="bar-chart" :size="20" />
                            </span>

                            <div class="min-w-[min(100%,280px)] flex-1">
                                <h3 id="analysis-result-title" class="font-bold tracking-[-0.015em] text-ink"
                                    :class="isMobile ? 'pt-1 text-lead' : 'text-[22px] leading-tight'">
                                    {{ result.visualization?.title || "Analysis completed" }}
                                </h3>
                                <p v-if="resultDescription && !isMobile" class="mt-1 text-body text-ink-muted">
                                    {{ resultDescription }}
                                </p>
                            </div>

                            <div v-if="!isMobile" class="flex shrink-0 items-center gap-2">
                                <span v-if="resultSource"
                                    class="inline-flex h-9 items-center rounded-[10px] bg-[#f0e9d9] px-4 text-data font-medium text-ink">
                                    {{ resultSource }}
                                </span>
                                <Tooltip :content="rowInfo">
                                    <span tabindex="0"
                                        class="inline-flex h-9 items-center gap-2 rounded-[10px] px-3 text-data text-ink"
                                        :class="result.data?.row_limit_reached ? 'bg-warn-soft text-warn-ink' : ''">
                                        <span class="tabular-nums">{{ formatNumber(returnedRowCount) }}
                                            {{ returnedRowCount === 1 ? "row" : "rows" }}</span>
                                        <Icon :name="result.data?.row_limit_reached ? 'warning' : 'info'" :size="16"
                                            :class="result.data?.row_limit_reached ? '' : 'text-ink-muted'" />
                                        <span class="sr-only">{{ rowInfo }}</span>
                                    </span>
                                </Tooltip>
                                <SegmentedControl v-if="canShowChart" v-model="resultView"
                                    :items="RESULT_VIEWS" label="Result view" size="sm" />
                                <Button v-if="inspectorDocked && !inspectorOpen" size="sm" icon="panel-right"
                                    :aria-pressed="false" @click="inspectorOpen = true">
                                    Findings<span v-if="insightCount" class="tabular-nums"> ({{ insightCount }})</span>
                                </Button>
                            </div>

                        </header>

                        <!-- Mobile: row limit + view switch under the title -->
                        <div v-if="isMobile" class="flex flex-wrap items-center gap-2 px-4 pt-3">
                            <span class="inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-caption"
                                :class="result.data?.row_limit_reached ? 'bg-warn-soft text-warn-ink' : 'bg-[#f0e9d9] text-ink'">
                                <Icon v-if="result.data?.row_limit_reached" name="warning" :size="14" />
                                {{ formatNumber(returnedRowCount) }} rows{{ result.data?.row_limit_reached ? " · limit reached" : "" }}
                            </span>
                            <SegmentedControl v-if="canShowChart" v-model="resultView" :items="RESULT_VIEWS"
                                label="Result view" size="sm" class="ml-auto" />
                        </div>

                        <!-- KPI tiles (desktop) -->
                        <dl v-if="kpiTiles.length && !isMobile" class="grid grid-cols-2 gap-3 px-6 pt-5 @min-[760px]:grid-cols-4">
                            <div v-for="tile in kpiTiles" :key="tile.key"
                                class="flex min-w-0 items-center gap-3 rounded-[12px] border border-[#ebe3d2] bg-[#fbf8f0] px-3.5 py-3.5">
                                <span aria-hidden="true" class="grid h-10 w-10 shrink-0 place-items-center rounded-[10px]"
                                    :class="tile.tile">
                                    <Icon :name="tile.icon" :size="20" />
                                </span>
                                <!-- The value scales with the tile's width (container
                                     units), so the full number always fits. -->
                                <div class="@container/kpi min-w-0 flex-1">
                                    <dt class="line-clamp-2 text-data font-medium leading-snug text-ink">{{ tile.label }}</dt>
                                    <dd class="whitespace-nowrap text-[clamp(14px,15cqi,21px)] font-bold leading-tight tracking-[-0.01em] tabular-nums text-ink"
                                        :title="formatNumber(tile.value)">
                                        {{ formatNumber(tile.value) }}
                                    </dd>
                                    <dd v-if="tile.sub" class="truncate text-caption text-ink-muted">{{ tile.sub }}</dd>
                                </div>
                            </div>
                        </dl>

                        <!-- Chart + plotted values / table -->

                        <div class="flex min-h-0 flex-col px-4 pb-4 pt-4 sm:px-6 sm:pb-6"
                            :class="isMobile ? '' : 'min-h-[340px] flex-1'">

                            <div v-if="canShowChart && resultView === 'chart'" class="grid min-h-0 flex-1 gap-4"
                                :class="showSideTable && !isMobile ? '@min-[760px]:grid-cols-[minmax(0,1fr)_300px]' : ''">

                                <div class="flex min-h-[300px] flex-col rounded-[12px]"
                                    :class="isMobile ? 'h-[280px]' : 'border border-[#efe8da] bg-[#fdfbf6] px-2 pb-2 pt-1'">
                                    <AnalyticsChart :result="result" ranked bare />
                                </div>

                                <div v-if="showSideTable && !isMobile"
                                    class="hidden self-start overflow-hidden rounded-[12px] bg-[#f6f1e5] @min-[760px]:block">
                                    <table class="w-full text-left">
                                        <caption class="sr-only">Plotted values</caption>
                                        <thead>
                                            <tr class="text-data font-semibold text-ink">
                                                <th scope="col" class="px-4 py-3">{{ capitalize(summary.xColumn) }}</th>
                                                <th scope="col" class="px-3 py-3 text-right">{{ capitalize(metricName) }}</th>
                                                <th v-if="showShare" scope="col" class="px-4 py-3 text-right">
                                                    <Tooltip content="Share of the total of the rows shown">
                                                        <span tabindex="0">Share</span>
                                                    </Tooltip>
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody class="bg-[#fbf8f0] text-data text-ink">
                                            <tr v-for="(row, index) in summary.rows" :key="index" class="border-t border-[#ece5d6]">
                                                <td class="max-w-[110px] truncate px-4 py-2.5" :title="String(row?.[summary.xColumn] ?? '')">
                                                    {{ formatCell(row?.[summary.xColumn]) }}
                                                </td>
                                                <td class="px-3 py-2.5 text-right tabular-nums">{{ formatCell(row?.[summary.yColumn]) }}</td>
                                                <td v-if="showShare" class="px-4 py-2.5 text-right tabular-nums">{{ shareFor(row) }}</td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                            <!-- Table: table results, and the Table view of chart results -->
                            <div v-else-if="isTableResult || canShowChart"
                                class="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[12px] border border-[#ebe3d2]"
                                :class="isMobile ? 'max-h-[420px]' : ''">

                                <div class="min-h-0 flex-1 overflow-auto [scrollbar-width:thin]">
                                    <table class="w-full min-w-[480px] border-separate border-spacing-0 text-left">
                                        <thead class="sticky top-0 z-10">
                                            <tr>
                                                <th v-for="column in result.data?.columns || []" :key="column" scope="col"
                                                    class="whitespace-nowrap border-b border-[#ebe3d2] bg-[#f6f1e5] px-4 py-2.5 text-data font-semibold text-ink"
                                                    :class="tableRows.some((row) => typeof row?.[column] === 'number') ? 'text-right' : ''">
                                                    {{ column }}
                                                </th>
                                            </tr>
                                        </thead>
                                        <tbody class="bg-[#fdfbf6] text-data">
                                            <tr v-for="(row, index) in tableRows" :key="index"
                                                class="transition-colors duration-150 hover:bg-canvas">
                                                <td v-for="column in result.data?.columns || []" :key="column"
                                                    class="whitespace-nowrap border-b border-[#efe8da] px-4 py-2.5 text-ink"
                                                    :class="typeof row?.[column] === 'number' ? 'text-right tabular-nums' : ''">
                                                    {{ formatCell(row?.[column]) }}
                                                </td>
                                            </tr>
                                            <tr v-if="!result.data?.rows?.length">
                                                <td :colspan="result.data?.columns?.length || 1" class="p-0">
                                                    <EmptyState icon="table" title="No rows were returned." />
                                                </td>
                                            </tr>
                                        </tbody>
                                    </table>
                                </div>

                                <p class="shrink-0 border-t border-[#ebe3d2] bg-[#f8f4ea] px-4 py-2 text-caption text-ink-muted">
                                    <span class="tabular-nums">{{ formatNumber(returnedRowCount) }}</span> rows
                                    <template v-if="tableRowsHidden">
                                        - showing the first <span class="tabular-nums">{{ formatNumber(tableRows.length) }}</span> of
                                        <span class="tabular-nums">{{ formatNumber(result.data?.rows?.length) }}</span> returned rows.
                                    </template>
                                </p>
                            </div>

                            <!-- Nothing visualizable -->
                            <EmptyState v-else-if="!result.visualization && !result.data?.rows?.length && !result.insights?.insights?.length"
                                icon="sparkle" title="Analysis completed"
                                description="The analysis did not return visualizable results." />

                            <!-- Mobile: KPI summary 2 x 2 + View findings -->
                            <template v-if="isMobile">
                                <dl v-if="kpiTiles.length" class="mt-4 grid grid-cols-2 gap-2">
                                    <div v-for="tile in kpiTiles" :key="tile.key"
                                        class="min-w-0 rounded-[12px] border border-[#ebe3d2] bg-[#fbf8f0] px-3 py-2.5">
                                        <dt class="flex items-center gap-1.5 truncate text-caption font-medium text-ink">
                                            <span aria-hidden="true" class="grid h-5 w-5 place-items-center rounded-[6px]" :class="tile.tile">
                                                <Icon :name="tile.icon" :size="14" />
                                            </span>
                                            {{ tile.label }}
                                        </dt>
                                        <dd class="mt-1 truncate text-lead font-bold tabular-nums text-ink">{{ formatCompactNumber(tile.value) }}</dd>
                                        <dd v-if="tile.sub" class="truncate text-caption text-ink-muted">{{ tile.sub }}</dd>
                                    </div>
                                </dl>
                                <button type="button"
                                    class="mt-4 flex h-12 w-full items-center justify-center gap-2 rounded-[12px] bg-[#f1ebdd] text-body font-semibold text-ink transition-colors duration-150 hover:bg-[#ebe3d2]"
                                    @click="viewFindings">
                                    View findings
                                    <Icon name="chevron-right" :size="16" />
                                </button>
                            </template>

                        </div>

                    </section>

                </Transition>

            </div>

            <!-- =====================================================
                 RIGHT COLUMN: findings / calculation + next questions
            ====================================================== -->

            <template v-if="result" #inspector>

                <div v-if="inspectorDocked" class="flex flex-col gap-4 pb-6 pl-1 pr-6 pt-[124px]">

                    <Tabs v-model="inspectorTab" :items="INSPECTOR_TABS" label="Result details"
                        class="overflow-hidden rounded-[16px] border border-[#e6decd] bg-surface shadow-panel [&>div:first-child]:px-4">
                        <template #end>
                            <Tooltip content="Hide panel">
                                <button type="button" aria-label="Hide findings panel"
                                    class="grid h-8 w-8 place-items-center rounded-control text-ink-muted transition-colors hover:bg-sunken hover:text-ink"
                                    @click="inspectorOpen = false">
                                    <Icon name="panel-right" :size="16" />
                                </button>
                            </Tooltip>
                        </template>

                        <TabPanel value="findings" class="py-2">
                            <AnalyticsInsights v-if="result.insights?.insights?.length" :result="result" />
                            <!-- `result` is only set after a successful response, so
                                 these never show while loading or after a failure. -->
                            <p v-else-if="result.insight_status === 'success'" class="px-5 py-3 text-data text-ink-muted">
                                No insights are supported by this result.
                            </p>
                            <p v-if="result.insight_status === 'unavailable'" :title="result.insight_error || undefined"
                                class="px-5 py-3 text-data text-ink-muted">
                                Insights unavailable for this result.
                            </p>
                        </TabPanel>

                        <!-- Built from the executed plan. Text interpolation (never
                             v-html) keeps column names and filter values as text. -->
                        <TabPanel v-if="planExplanation" value="calculation" class="px-5 py-4">
                            <p class="text-caption text-ink-muted">
                                How this result was produced ({{ planExplanation.interpretedBy }}).
                            </p>
                            <ol class="mt-4">
                                <li v-for="(step, index) in planExplanation.steps" :key="`step-${index}`"
                                    class="relative flex gap-3 pb-4 last:pb-0">
                                    <span v-if="index < planExplanation.steps.length - 1" aria-hidden="true"
                                        class="absolute bottom-0 left-[13px] top-7 w-px bg-line"></span>
                                    <span aria-hidden="true"
                                        class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#e4eedd] text-caption font-semibold text-forest">
                                        {{ index + 1 }}
                                    </span>
                                    <span class="min-w-0 break-words pt-1 text-data text-ink">{{ step }}</span>
                                </li>
                            </ol>
                            <ul v-if="planExplanation.limitations.length"
                                class="mt-5 space-y-1.5 rounded-control border border-warn-ink/15 bg-warn-soft px-3 py-2.5 text-caption text-warn-ink">
                                <li v-for="(limitation, index) in planExplanation.limitations" :key="`limitation-${index}`"
                                    class="flex items-start gap-1.5 break-words">
                                    <Icon name="warning" :size="14" class="mt-px" />
                                    <span>{{ limitation }}</span>
                                </li>
                            </ul>
                        </TabPanel>
                    </Tabs>

                    <section v-if="nextQuestions.length" aria-labelledby="next-questions-title"
                        class="rounded-[16px] border border-[#e6decd] bg-surface px-4 pb-3 pt-4 shadow-panel">
                        <h4 id="next-questions-title" class="px-1 text-lead font-semibold text-ink">Next questions</h4>
                        <ul class="mt-2">
                            <li v-for="item in nextQuestions" :key="item.key">
                                <button type="button" :disabled="loading"
                                    class="flex w-full items-start gap-3 rounded-[10px] px-1 py-2 text-left text-data text-ink transition-colors duration-150 hover:bg-sunken/60 disabled:opacity-50"
                                    @click="chooseNextQuestion(item)">
                                    <span aria-hidden="true"
                                        class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#f1ebdd] text-ink-muted">
                                        <Icon name="arrow-right" :size="14" />
                                    </span>
                                    <span class="pt-1">{{ item.label }}</span>
                                </button>
                            </li>
                        </ul>
                    </section>
                </div>

                <!-- Stacked (mobile / tablet): accessible accordions -->
                <div v-else id="analyze-findings" class="scroll-mt-4 px-4 pb-6 pt-1 sm:px-6">
                    <AccordionRoot v-model="stackedSections" type="multiple"
                        class="overflow-hidden rounded-[16px] border border-[#e6decd] bg-surface shadow-panel">

                        <AccordionItem value="findings" class="border-b border-line last:border-b-0">
                            <AccordionHeader as="h4">
                                <AccordionTrigger
                                    class="group flex min-h-12 w-full items-center gap-2.5 px-4 text-left text-body font-semibold text-ink hover:bg-sunken/50">
                                    Findings
                                    <span v-if="insightCount" class="text-caption font-normal tabular-nums text-ink-muted">{{ insightCount }}</span>
                                    <Icon name="chevron-down" :size="16"
                                        class="ml-auto text-ink-muted transition-transform duration-150 group-data-[state=open]:rotate-180" />
                                </AccordionTrigger>
                            </AccordionHeader>
                            <AccordionContent class="pb-2">
                                <AnalyticsInsights v-if="result.insights?.insights?.length" :result="result" />
                                <p v-else-if="result.insight_status === 'success'" class="px-4 pb-2 text-data text-ink-muted">
                                    No insights are supported by this result.
                                </p>
                                <p v-if="result.insight_status === 'unavailable'" :title="result.insight_error || undefined"
                                    class="px-4 pb-2 text-data text-ink-muted">
                                    Insights unavailable for this result.
                                </p>
                            </AccordionContent>
                        </AccordionItem>

                        <AccordionItem v-if="planExplanation" value="calculation" class="border-b border-line last:border-b-0">
                            <AccordionHeader as="h4">
                                <AccordionTrigger
                                    class="group flex min-h-12 w-full items-center gap-2.5 px-4 text-left text-body font-semibold text-ink hover:bg-sunken/50">
                                    Calculation
                                    <Icon name="chevron-down" :size="16"
                                        class="ml-auto text-ink-muted transition-transform duration-150 group-data-[state=open]:rotate-180" />
                                </AccordionTrigger>
                            </AccordionHeader>
                            <AccordionContent class="px-4 pb-4">
                                <p class="mb-3 text-caption text-ink-muted">{{ planExplanation.interpretedBy }}</p>
                                <ol class="space-y-2.5">
                                    <li v-for="(step, index) in planExplanation.steps" :key="`step-${index}`" class="flex gap-3">
                                        <span aria-hidden="true"
                                            class="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[#e4eedd] text-caption font-semibold text-forest">
                                            {{ index + 1 }}
                                        </span>
                                        <span class="min-w-0 break-words pt-0.5 text-data text-ink">{{ step }}</span>
                                    </li>
                                </ol>
                                <ul v-if="planExplanation.limitations.length" class="mt-3 space-y-1 text-caption text-warn-ink">
                                    <li v-for="(limitation, index) in planExplanation.limitations" :key="`limitation-${index}`"
                                        class="flex items-start gap-1.5 break-words">
                                        <Icon name="warning" :size="14" class="mt-px" />
                                        <span>{{ limitation }}</span>
                                    </li>
                                </ul>
                            </AccordionContent>
                        </AccordionItem>

                        <AccordionItem v-if="nextQuestions.length" value="next">
                            <AccordionHeader as="h4">
                                <AccordionTrigger
                                    class="group flex min-h-12 w-full items-center gap-2.5 px-4 text-left text-body font-semibold text-ink hover:bg-sunken/50">
                                    Next questions
                                    <Icon name="chevron-down" :size="16"
                                        class="ml-auto text-ink-muted transition-transform duration-150 group-data-[state=open]:rotate-180" />
                                </AccordionTrigger>
                            </AccordionHeader>
                            <AccordionContent class="px-3 pb-3">
                                <button v-for="item in nextQuestions" :key="item.key" type="button" :disabled="loading"
                                    class="flex w-full items-start gap-3 rounded-[10px] px-1 py-2 text-left text-data text-ink hover:bg-sunken/60"
                                    @click="chooseNextQuestion(item)">
                                    <Icon name="arrow-right" :size="16" class="mt-0.5 shrink-0 text-ink-muted" />
                                    {{ item.label }}
                                </button>
                            </AccordionContent>
                        </AccordionItem>

                    </AccordionRoot>
                </div>

            </template>

        </InspectorFrame>

    </section>
</template>
