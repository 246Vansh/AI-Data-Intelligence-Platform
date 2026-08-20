import axios from "axios";

const api = axios.create({
    baseURL: "http://127.0.0.1:8000/api",
    headers: {
        "Content-Type": "application/json",
    },
});


// =========================================================
// DATASET
// =========================================================

export async function getDatasetProfile() {
    const response = await api.get("/dataset/profile");

    return response.data;
}


export async function getDatasetPreview() {
    const response = await api.get("/dataset/preview");

    return response.data;
}


export async function getDatasetMetadata() {
    const response = await api.get("/dataset/metadata");

    return response.data;
}


// =========================================================
// ANALYSIS
// =========================================================

export async function analyzeDataset(question) {
    if (!question || !question.trim()) {
        throw new Error("Analysis question cannot be empty.");
    }

    const response = await api.post("/analyze", {
        question: question.trim(),
    });

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