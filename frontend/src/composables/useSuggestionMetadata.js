import { computed, getCurrentScope, onScopeDispose, ref, toValue } from "vue";

import {
    datasetUrls,
    getApiErrorMessage,
    getCachedResponse,
    getDatasetMetadata,
    onCachedResponse,
} from "../services/api.js";
import { useDatasetResource } from "./useDatasetResource.js";

// =========================================================
// SUGGESTION METADATA (Analyze workspace)
// =========================================================
//
// /metadata feeds ONLY the suggestion chips and the "next question"
// ideas - asking a question never needs it (the planner reads its own
// planning metadata on the server). Building it the first time is an
// exact per-column scan that runs on the analysis worker pool and holds
// the dataset's locks, so starting it while the user is about to ask a
// question would delay that question. Therefore:
//
// - it is requested ONLY by the explicit "Suggest questions" button
//   (requestSuggestions) - never on selection, focus or submit;
// - if /metadata is already in the browser cache (the Data or Schema
//   tab loaded it), the chips appear from that copy with no request,
//   including when it arrives later while this panel is mounted;
// - after a failed load the button is offered again as the retry;
// - comparison / cross-dataset modes use static suggestions and never
//   request it.
//
// `datasetId` and `analysisMode` are refs or getters.

export function useSuggestionMetadata({ datasetId, analysisMode }) {
    const wanted = ref(false);
    const isSingle = () => toValue(analysisMode) === "single";

    const resource = useDatasetResource({
        datasetId,
        active: () => wanted.value && isSingle(),
        fetch: (id, options) => getDatasetMetadata(id, options),
        errorMessage: (err) => getApiErrorMessage(err) || "Unable to load dataset metadata.",
    });

    // Already cached: adopt it. The resource's request is then a cache
    // hit in api.js cachedGet - no network request is sent.
    function adoptIfCached() {
        const id = toValue(datasetId);
        if (id && getCachedResponse(datasetUrls.metadata(id)) !== undefined) {
            wanted.value = true;
        }
    }

    adoptIfCached();

    const stopFollowing = onCachedResponse((url) => {
        const id = toValue(datasetId);
        if (id && url === datasetUrls.metadata(id)) {
            wanted.value = true;
        }
    });

    if (getCurrentScope()) {
        onScopeDispose(stopFollowing);
    }

    function requestSuggestions() {
        if (!toValue(datasetId) || !isSingle()) {
            return;
        }
        if (wanted.value && resource.error.value && !resource.loading.value) {
            resource.load(); // retry after a failure
            return;
        }
        wanted.value = true;
    }

    // Offered until suggestions are requested, and again after a failure.
    const showSuggestButton = computed(() =>
        Boolean(toValue(datasetId)) &&
        isSingle() &&
        (!wanted.value || (Boolean(resource.error.value) && !resource.loading.value)),
    );

    return {
        data: resource.data,
        loading: resource.loading,
        error: resource.error,
        showSuggestButton,
        requestSuggestions,
    };
}
