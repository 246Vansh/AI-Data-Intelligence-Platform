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

async function cachedGet(url) {
    if (cache.has(url)) {
        return cache.get(url);
    }

    if (inFlight.has(url)) {
        return inFlight.get(url);
    }

    const promise = api
        .get(url)
        .then((response) => {
            cache.set(url, response.data);
            inFlight.delete(url);
            return response.data;
        })
        .catch((error) => {
            inFlight.delete(url);
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

export async function getDatasetProfile(datasetId) {
    return cachedGet(
        datasetId ? `/dataset/${datasetId}/profile` : "/dataset/profile",
    );
}

export async function getDatasetPreview(datasetId) {
    return cachedGet(
        datasetId ? `/dataset/${datasetId}/preview` : "/dataset/preview",
    );
}

export async function getDatasetMetadata(datasetId) {
    return cachedGet(
        datasetId ? `/dataset/${datasetId}/metadata` : "/dataset/metadata",
    );
}

export async function getDatasetQuality() {
    return cachedGet("/dataset/quality");
}



// =========================================================
// ANALYSIS
// =========================================================

export async function analyzeDataset(question, datasetId, analysisContext) {
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

    const response = await api.post("/analyze", payload);

    return response.data;
}


// =========================================================
// ERROR HANDLING
// =========================================================

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