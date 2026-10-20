import axios from "axios";

const api = axios.create({
    baseURL: import.meta.env?.VITE_API_BASE_URL || "/api",
    headers: {
        "Content-Type": "application/json",
    },
});


// =========================================================
// IN-MEMORY CLIENT CACHE & REQUEST DEDUPLICATION
// =========================================================

const cache = new Map();
const inFlight = new Map();

export function clearDatasetCache() {
    cache.clear();
    inFlight.clear();
}

// Drops every cached / in-flight entry scoped to one dataset_id
// (the `/dataset/{id}/...` URLs), leaving other datasets' entries
// untouched.
export function evictDatasetCache(datasetId) {
    const prefix = `/dataset/${datasetId}/`;

    for (const store of [cache, inFlight]) {
        for (const url of store.keys()) {
            if (url.startsWith(prefix)) {
                store.delete(url);
            }
        }
    }
}

// Listeners notified when a dataset-scoped request comes back 404,
// i.e. the dataset no longer exists for this user (deleted elsewhere,
// or lost by the backend).
const datasetMissingListeners = new Set();

export function onDatasetMissing(listener) {
    datasetMissingListeners.add(listener);
    return () => datasetMissingListeners.delete(listener);
}

// `datasetId` is passed only for `/dataset/{id}/...` requests, so a
// 404 from any other endpoint is never treated as a deleted dataset.
// `force` skips the cached copy (a user-requested refresh); an
// identical request already in flight is still shared.
async function cachedGet(url, datasetId, { force = false } = {}) {
    if (force) {
        cache.delete(url);
    }

    if (cache.has(url)) {
        return cache.get(url);
    }

    if (inFlight.has(url)) {
        return inFlight.get(url);
    }

    const promise = api
        .get(url)
        .then((response) => {
            // Skip caching if this entry was evicted while in flight
            // (e.g. the dataset was deleted mid-request).
            if (inFlight.get(url) === promise) {
                cache.set(url, response.data);
                inFlight.delete(url);
            }
            return response.data;
        })
        .catch((error) => {
            if (inFlight.get(url) === promise) {
                inFlight.delete(url);
            }

            if (datasetId && error?.response?.status === 404) {
                evictDatasetCache(datasetId);
                datasetMissingListeners.forEach((listener) => listener(datasetId));
            }

            throw error;
        });

    inFlight.set(url, promise);
    return promise;
}

// =========================================================
// DATASET
// =========================================================

export async function uploadDataset(file) {
    clearDatasetCache();

    const formData = new FormData();
    formData.append("file", file);

    const response = await api.post(
        "/dataset/upload",
        formData,
        {
            headers: {
                "Content-Type": "multipart/form-data",
            },
        },
    );

    return response.data;
}

export async function listDatasets() {
    const response = await api.get("/dataset");
    return response.data;
}

export async function deleteDataset(datasetId) {
    const response = await api.delete(`/dataset/${datasetId}`);
    evictDatasetCache(datasetId);
    return response.data;
}

// Dataset-scoped reads always name their dataset: the un-scoped
// `/dataset/profile`-style routes resolve the server's global "active
// dataset", which can differ from the one this UI has selected.
function requireDatasetId(datasetId) {
    if (!datasetId) {
        throw new Error("No dataset selected.");
    }
}

export async function getDatasetProfile(datasetId, options) {
    requireDatasetId(datasetId);
    return cachedGet(`/dataset/${datasetId}/profile`, datasetId, options);
}

export async function getDatasetPreview(datasetId, options) {
    requireDatasetId(datasetId);
    return cachedGet(`/dataset/${datasetId}/preview`, datasetId, options);
}

export async function getDatasetMetadata(datasetId, options) {
    requireDatasetId(datasetId);
    return cachedGet(`/dataset/${datasetId}/metadata`, datasetId, options);
}

export async function getDatasetQuality(datasetId, options) {
    requireDatasetId(datasetId);
    return cachedGet(`/dataset/${datasetId}/quality`, datasetId, options);
}



// =========================================================
// ANALYSIS
// =========================================================

// `signal` (AbortController) lets the caller abandon a superseded
// request client-side. The server is not told to stop: work already
// queued on its analysis pool still runs.
export async function analyzeDataset(question, datasetId, analysisContext, { signal } = {}) {
    if (!question || !question.trim()) {
        throw new Error("Analysis question cannot be empty.");
    }

    if (!datasetId) {
        throw new Error("No dataset selected. Please upload a dataset first.");
    }

    const payload = {
        question: question.trim(),
        dataset_id: datasetId,
    };

    // `analysis_context` (mode + full dataset_ids[] + primary_dataset_id)
    // is additive - existing SINGLE-mode callers that omit it keep
    // working against the current dataset_id-only contract untouched.
    if (analysisContext) {
        payload.analysis_context = analysisContext;
    }

    try {
        const response = await api.post("/analyze", payload, { signal });
        return response.data;
    } catch (error) {
        // Same dataset-missing recovery as cachedGet(), keyed on the
        // dataset_id this request was sent for.
        if (error?.response?.status === 404) {
            evictDatasetCache(datasetId);
            datasetMissingListeners.forEach((listener) => listener(datasetId));
        }

        throw error;
    }
}


// =========================================================
// ERROR HANDLING
// =========================================================

export function isRequestCancelled(error) {
    return axios.isCancel(error);
}

export function getApiErrorMessage(error) {
    if (error.response) {
        const detail = error.response.data?.detail;

        if (typeof detail === "string") {
            return detail;
        }

        if (Array.isArray(detail)) {
            return detail
                .map((item) => item?.msg || "Validation error")
                .join(", ");
        }

        return `Request failed with status ${error.response.status}.`;
    }

    if (error.request) {
        return "Unable to connect to the analysis server.";
    }

    return error.message || "An unexpected error occurred.";
}