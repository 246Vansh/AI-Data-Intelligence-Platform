import { ref, computed } from "vue";

// =========================================================
// ANALYSIS CONTEXT
// =========================================================
//
// Centralizes the "which dataset(s) is the app currently analyzing,
// and how" concept on top of the existing dataset store (the
// `datasets` list owned by Dashboard.vue). This does not duplicate
// dataset data - it only tracks selected dataset_ids and the
// current analysis mode, and resolves dataset metadata (name, rows,
// etc.) through the existing dataset state wherever it's needed.

export const ANALYSIS_MODES = {
    SINGLE: "single",
    COMPARISON: "comparison",
    CROSS_DATASET: "cross_dataset",
};

export const ANALYSIS_MODE_LABELS = {
    [ANALYSIS_MODES.SINGLE]: "Single",
    [ANALYSIS_MODES.COMPARISON]: "Compare",
    [ANALYSIS_MODES.CROSS_DATASET]: "Cross-Dataset",
};

export function useAnalysisContext() {
    const mode = ref(ANALYSIS_MODES.SINGLE);

    // Ordered dataset_ids currently part of the analysis context.
    // SINGLE mode always keeps this at length <= 1.
    const datasetIds = ref([]);

    // The dataset driving single-dataset-shaped panels (Overview,
    // Preview, Schema, Ask Your Data execution) regardless of mode -
    // in COMPARISON / CROSS_DATASET this is just the first/"anchor"
    // dataset until real multi-dataset execution exists.
    const primaryDatasetId = ref("");

    const analysisContext = computed(() => ({
        mode: mode.value,
        dataset_ids: datasetIds.value.slice(),
        primary_dataset_id: primaryDatasetId.value || null,
    }));

    function isSelected(datasetId) {
        return datasetIds.value.includes(datasetId);
    }

    // SINGLE-mode selection: picking a dataset always replaces the
    // current selection, matching the existing single-select UX.
    function selectSingle(datasetId) {
        if (!datasetId) {
            return;
        }

        datasetIds.value = [datasetId];
        primaryDatasetId.value = datasetId;
    }

    // COMPARISON / CROSS_DATASET selection: picking a dataset adds
    // or removes it from the active set.
    function toggleDataset(datasetId) {
        if (!datasetId) {
            return;
        }

        if (mode.value === ANALYSIS_MODES.SINGLE) {
            selectSingle(datasetId);
            return;
        }

        datasetIds.value = isSelected(datasetId)
            ? datasetIds.value.filter((id) => id !== datasetId)
            : [...datasetIds.value, datasetId];

        if (!isSelected(primaryDatasetId.value)) {
            primaryDatasetId.value = datasetIds.value[0] || "";
        }
    }

    function setMode(newMode) {
        if (
            !Object.values(ANALYSIS_MODES).includes(newMode) ||
            newMode === mode.value
        ) {
            return;
        }

        mode.value = newMode;

        if (newMode !== ANALYSIS_MODES.SINGLE) {
            return;
        }

        // Switching back to SINGLE must never silently leave
        // multiple datasets active: collapse to primary_dataset_id
        // when it's still part of the selection, otherwise fall
        // back to the first selected dataset.
        const collapsedId = isSelected(primaryDatasetId.value)
            ? primaryDatasetId.value
            : datasetIds.value[0] || "";

        datasetIds.value = collapsedId ? [collapsedId] : [];
        primaryDatasetId.value = collapsedId;
    }

    return {
        mode,
        datasetIds,
        primaryDatasetId,
        analysisContext,
        isSelected,
        selectSingle,
        toggleDataset,
        setMode,
    };
}
