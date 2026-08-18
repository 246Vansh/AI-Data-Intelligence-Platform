import axios from "axios";

const api = axios.create({
    baseURL: "http://127.0.0.1:8000/api",
    headers: {
        "Content-Type": "application/json",
    },
});


export async function getDatasetProfile() {
    const response = await api.get(
        "/dataset/profile"
    );

    return response.data;
}


export async function getDatasetPreview() {
    const response = await api.get(
        "/dataset/preview"
    );

    return response.data;
}


export async function getDatasetMetadata() {
    const response = await api.get(
        "/dataset/metadata"
    );

    return response.data;
}


export async function analyzeDataset(
    question
) {

    const response = await api.post(
        "/analyze",
        {
            question,
        }
    );

    return response.data;
}