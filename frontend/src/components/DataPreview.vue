<script setup>
import { onMounted, ref } from "vue";

import {
    getDatasetPreview,
} from "../services/api";

const dataset = ref(null);
const loading = ref(true);
const error = ref(null);

async function loadPreview() {
    try {
        loading.value = true;
        error.value = null;

        dataset.value = await getDatasetPreview();

    } catch (err) {
        console.error(err);

        error.value = "Unable to load dataset.";

    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    loadPreview();
});
</script>

<template>
    <section class="preview">

        <!-- =========================
             Header
        ========================== -->

        <div class="preview-header">

            <div class="section-title">

                <div class="section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="3" width="18" height="18" rx="3" />

                        <path d="M3 9h18" />

                        <path d="M9 9v12" />

                        <path d="M13 13h4" />

                        <path d="M13 17h4" />
                    </svg>
                </div>

                <div>
                    <h2>Data Preview</h2>

                    <p>
                        Preview the records available in your dataset
                    </p>
                </div>

            </div>


            <div v-if="dataset" class="dataset-info">
                <span class="status-dot"></span>

                {{ dataset.rows.length }} records
            </div>

        </div>


        <!-- =========================
             Loading
        ========================== -->

        <div v-if="loading" class="state-card">

            <div class="loader"></div>

            <div>
                <strong>
                    Loading dataset
                </strong>

                <p>
                    Preparing your data preview...
                </p>
            </div>

        </div>


        <!-- =========================
             Error
        ========================== -->

        <div v-else-if="error" class="state-card error-state">

            <div class="error-icon">
                !
            </div>

            <div>
                <strong>
                    Unable to load dataset
                </strong>

                <p>
                    {{ error }}
                </p>

                <button type="button" @click="loadPreview">
                    Try Again
                </button>
            </div>

        </div>


        <!-- =========================
             Dataset
        ========================== -->

        <div v-else-if="dataset" class="table-card">

            <div class="table-topbar">

                <div>

                    <h3>
                        Dataset Records
                    </h3>

                    <p>
                        Showing the available dataset preview
                    </p>

                </div>

                <div class="column-count">
                    {{ dataset.columns.length }} columns
                </div>

            </div>


            <div class="table-wrapper">

                <table>

                    <thead>

                        <tr>

                            <th v-for="column in dataset.columns" :key="column">
                                <span class="column-name">
                                    {{ column }}
                                </span>
                            </th>

                        </tr>

                    </thead>


                    <tbody>

                        <tr v-for="(row, index) in dataset.rows" :key="index">

                            <td v-for="column in dataset.columns" :key="column">
                                {{ row[column] }}
                            </td>

                        </tr>

                    </tbody>

                </table>

            </div>


            <div class="table-footer">

                <span>
                    Preview of
                    <strong>{{ dataset.rows.length }}</strong>
                    records
                </span>

                <span>
                    <strong>{{ dataset.columns.length }}</strong>
                    columns
                </span>

            </div>

        </div>

    </section>
</template>


<style scoped>
/* =========================
   Main
========================= */

.preview {
    width: 100%;
    margin-top: 30px;
}


/* =========================
   Header
========================= */

.preview-header {
    display: flex;

    align-items: center;
    justify-content: space-between;

    gap: 20px;

    margin-bottom: 18px;
}


.section-title {
    display: flex;

    align-items: center;

    gap: 12px;
}


.section-icon {
    width: 40px;
    height: 40px;

    display: flex;

    align-items: center;
    justify-content: center;

    border-radius: 11px;

    color: #2563eb;

    background:
        linear-gradient(135deg,
            #eff6ff,
            #e0e7ff);
}


.section-icon svg {
    width: 21px;
    height: 21px;
}


.section-title h2 {
    margin: 0;

    color: #172033;

    font-size: 20px;

    font-weight: 700;

    letter-spacing: -0.3px;
}


.section-title p {
    margin: 3px 0 0;

    color: #7a8496;

    font-size: 13px;
}


/* =========================
   Dataset Info
========================= */

.dataset-info {
    display: flex;

    align-items: center;

    gap: 7px;

    padding: 7px 11px;

    border-radius: 999px;

    background: #ecfdf5;

    color: #047857;

    font-size: 11px;

    font-weight: 650;

    white-space: nowrap;
}


.status-dot {
    width: 7px;
    height: 7px;

    border-radius: 50%;

    background: #10b981;
}


/* =========================
   Table Card
========================= */

.table-card {
    overflow: hidden;

    border: 1px solid #e7e9f0;

    border-radius: 18px;

    background: #ffffff;

    box-shadow:
        0 5px 15px rgba(15, 23, 42, 0.03),
        0 14px 30px rgba(15, 23, 42, 0.04);
}


/* =========================
   Table Topbar
========================= */

.table-topbar {
    display: flex;

    align-items: center;
    justify-content: space-between;

    gap: 20px;

    padding: 18px 20px;

    border-bottom: 1px solid #edf0f5;

    background:
        linear-gradient(180deg,
            #ffffff,
            #fcfcfe);
}


.table-topbar h3 {
    margin: 0;

    color: #172033;

    font-size: 14px;

    font-weight: 700;
}


.table-topbar p {
    margin: 4px 0 0;

    color: #98a2b3;

    font-size: 11px;
}


.column-count {
    padding: 6px 10px;

    border-radius: 8px;

    background: #f5f3ff;

    color: #6d28d9;

    font-size: 11px;

    font-weight: 650;

    white-space: nowrap;
}


/* =========================
   Table
========================= */

.table-wrapper {
    width: 100%;

    overflow-x: auto;
}


table {
    width: 100%;

    min-width: 750px;

    border-collapse: collapse;
}


th,
td {
    padding: 13px 17px;

    text-align: left;

    border-bottom: 1px solid #edf0f5;

    white-space: nowrap;
}


/* Header */

th {
    position: sticky;

    top: 0;

    z-index: 1;

    background: #fcf8ff;

    color: black;

    font-size: 11px;

    font-weight: 700;

    text-transform: uppercase;

    letter-spacing: 0.35px;
}


.column-name {
    display: inline-flex;

    align-items: center;

    max-width: 220px;

    overflow: hidden;

    text-overflow: ellipsis;
}


/* Cells */

td {
    color: #475467;

    font-size: 12px;
}


tbody tr {
    transition:
        background-color 0.15s ease;
}


tbody tr:hover {
    background: #faf9ff;
}


tbody tr:last-child td {
    border-bottom: none;
}


/* =========================
   Footer
========================= */

.table-footer {
    display: flex;

    align-items: center;
    justify-content: space-between;

    gap: 15px;

    padding: 12px 18px;

    border-top: 1px solid #edf0f5;

    background: #fcfcfd;

    color: #98a2b3;

    font-size: 11px;
}


.table-footer strong {
    color: #667085;

    font-weight: 650;
}


/* =========================
   Loading / Error
========================= */

.state-card {
    display: flex;

    align-items: center;

    gap: 14px;

    padding: 22px 24px;

    border: 1px solid #e8eaf1;

    border-radius: 16px;

    background: #ffffff;

    color: #667085;
}


.state-card strong {
    display: block;

    margin-bottom: 4px;

    color: #172033;

    font-size: 14px;
}


.state-card p {
    margin: 0;

    font-size: 13px;
}


/* Loader */

.loader {
    width: 28px;
    height: 28px;

    flex-shrink: 0;

    border: 3px solid #ede9fe;

    border-top-color: #7c3aed;

    border-radius: 50%;

    animation:
        spin 0.8s linear infinite;
}


@keyframes spin {

    to {
        transform: rotate(360deg);
    }

}


/* =========================
   Error
========================= */

.error-state {
    border-color: #fecaca;

    background: #fffafa;
}


.error-icon {
    width: 36px;
    height: 36px;

    display: flex;

    align-items: center;
    justify-content: center;

    flex-shrink: 0;

    border-radius: 50%;

    background: #fee2e2;

    color: #dc2626;

    font-weight: 700;
}


.error-state button {
    margin-top: 10px;

    padding: 7px 12px;

    border: none;

    border-radius: 8px;

    background: #7c3aed;

    color: #ffffff;

    font-size: 12px;

    font-weight: 600;

    cursor: pointer;

    transition:
        background 0.2s ease;
}


.error-state button:hover {
    background: #6d28d9;
}


/* =========================
   Responsive
========================= */

@media (max-width: 700px) {

    .preview-header {
        align-items: flex-start;

        flex-direction: column;
    }


    .dataset-info {
        align-self: flex-start;
    }


    .table-topbar {
        align-items: flex-start;

        flex-direction: column;
    }


    .table-footer {
        align-items: flex-start;

        flex-direction: column;
    }

}
</style>