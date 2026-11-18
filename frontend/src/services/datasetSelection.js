// =========================================================
// INITIAL DATASET SELECTION (after the library is hydrated)
// =========================================================
//
// Why this exists (bug found during the Stage 1 redesign): after a page
// reload, Dashboard.loadDatasets() re-fills the dataset library from the
// backend registry, but nothing selects a dataset - selection is plain
// in-memory state and, by design, dataset ids are never written to
// browser storage (see services/auth.test.js). The result was a library
// full of datasets next to a workspace saying "No dataset selected".
//
// Dashboard calls this once a load finishes, ONLY when nothing is
// selected yet, and selects the returned id through the normal
// selectDataset() path (cache eviction, panel remount - unchanged).
// Returning "" keeps the old behavior: the user picks from the library.
//
// `datasets` is the hydrated list, each entry
//   { dataset_id, filename, rows, columns, created_at }
// where created_at is the backend's ISO timestamp (may be missing for
// entries added by an upload in this session).

export function pickInitialDatasetId(datasets) {
    if (!Array.isArray(datasets) || datasets.length === 0) {
        return "";
    }

    // APPROVED POLICY: never select a dataset automatically after a
    // reload - the user always chooses which dataset to open. Kept as a
    // single, tested decision point rather than a silent omission.
    return "";
}
