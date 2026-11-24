import { ref, toValue, watch } from "vue";

import { getApiErrorMessage } from "../services/api.js";

// =========================================================
// DEMAND-DRIVEN DATASET RESOURCE
// =========================================================
//
// One dataset-scoped read (preview, metadata, quality audit, ...) that
// is requested only when it is needed, not when its panel mounts.
// Workspace panels are never unmounted (see ui/Tabs.vue), and profile/
// metadata/quality builds are expensive on the server: they run on the
// bounded analysis worker pool and hold the dataset's locks, delaying
// the user's own questions. So:
//
// - nothing is requested while `active` is false;
// - the first time it is active for a dataset, it is requested once;
// - becoming inactive and active again reuses what was loaded (or the
//   request still in flight - api.js cachedGet also shares requests);
// - load({ refresh: true }) is an explicit reload: `fetch` receives
//   { force: true }, which bypasses the BROWSER cache only;
// - a dataset change forgets the previous dataset's state, and a late
//   response for a superseded request is ignored.
//
// State:
// - loading:    a first load (or retry) is in flight;
// - refreshing: an explicit reload is in flight (the loaded data stays);
// - settled:    a response or an error exists for the current dataset -
//               false before the first request, so a panel can show its
//               loading frame instead of an empty result.
//
// `datasetId` and `active` are refs or getters. `fetch(datasetId,
// { force })` returns a promise; `errorMessage(err)` turns a failure
// into the text shown.

export function useDatasetResource({
    datasetId,
    active,
    fetch,
    errorMessage = getApiErrorMessage,
}) {
    const data = ref(null);
    const loading = ref(false);
    const refreshing = ref(false);
    const error = ref(null);
    const settled = ref(false);

    // Dataset whose resource was requested; null before the first request.
    let requestedFor = null;
    let latest = 0;

    async function load({ refresh = false } = {}) {
        const id = toValue(datasetId);
        if (!id) {
            return;
        }

        requestedFor = id;
        const request = ++latest;
        const isRefresh = refresh === true;

        if (isRefresh) {
            refreshing.value = true;
            loading.value = false;
        } else {
            loading.value = true;
            refreshing.value = false;
        }
        error.value = null;

        try {
            const result = await fetch(id, { force: isRefresh });
            if (request === latest) {
                data.value = result;
            }
        } catch (err) {
            if (request === latest) {
                error.value = errorMessage(err);
            }
        } finally {
            if (request === latest) {
                loading.value = false;
                refreshing.value = false;
                settled.value = true;
            }
        }
    }

    function reset() {
        requestedFor = null;
        latest += 1;
        data.value = null;
        error.value = null;
        loading.value = false;
        refreshing.value = false;
        settled.value = false;
    }

    watch(
        [() => toValue(datasetId), () => Boolean(toValue(active))],
        ([id, isActive]) => {
            if (requestedFor !== null && id !== requestedFor) {
                reset();
            }

            if (id && isActive && requestedFor === null) {
                load();
            }
        },
        { immediate: true },
    );

    return {
        data,
        loading,
        refreshing,
        error,
        settled,
        load,
        refresh: () => load({ refresh: true }),
    };
}
