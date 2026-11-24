import { computed } from "vue";

import { getApiErrorMessage, getDatasetQuality } from "../services/api.js";
import { useDatasetResource } from "./useDatasetResource.js";

// =========================================================
// DEMAND-DRIVEN QUALITY AUDIT
// =========================================================
//
// A first-time quality audit is expensive on the server (a full-row
// duplicate scan plus per-column statistics and quartiles; ~90 s at 10M
// rows) and runs on the same bounded worker pool as analysis, so it is
// requested only when the Quality workspace is first activated - see
// useDatasetResource for the shared rules (once per dataset, reuse on
// return, stale responses ignored).
//
// `refresh()` is the explicit Refresh. It bypasses the browser cache
// only - the server answers from its own cached audit. As before the
// shared helper existed, `loading` covers both the first load and a
// Refresh (the Quality panel shows its loading frame for both).
//
// `datasetId` and `active` are refs or getters. `fetchQuality` and
// `errorMessage` are injectable for tests.

export function useQualityAudit({
    datasetId,
    active,
    fetchQuality = getDatasetQuality,
    errorMessage = getApiErrorMessage,
}) {
    const resource = useDatasetResource({
        datasetId,
        active,
        fetch: fetchQuality,
        errorMessage,
    });

    return {
        data: resource.data,
        loading: computed(() => resource.loading.value || resource.refreshing.value),
        error: resource.error,
        load: resource.load,
        refresh: resource.refresh,
    };
}
