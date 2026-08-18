<script setup>
import { ref } from "vue";

import { analyzeDataset } from "../services/api";

import AnalyticsChart from "./AnalyticsChart.vue";

const question = ref(
    "Show me the top 5 stores by average weekly sales during holidays."
);

const loading = ref(false);
const error = ref(null);
const result = ref(null);

async function analyze() {
    try {
        loading.value = true;
        error.value = null;
        result.value = null;

        const response = await analyzeDataset(question.value);

        if (!response.success) {
            error.value =
                response.error?.message ||
                "Unable to analyze the dataset.";

            return;
        }

        result.value = response;

    } catch (err) {
        console.error(err);

        error.value =
            err.response?.data?.detail ||
            "Unable to analyze dataset.";

    } finally {
        loading.value = false;
    }
}
</script>

<template>
    <section class="analytics-builder">

        <!-- =========================
             Ask Your Data
        ========================== -->

        <div class="analytics-card">

            <!-- Header -->

            <div class="section-header">

                <div class="section-title">

                    <div class="section-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M21 11.5a8.38 8.38 0 0 1-9 8.3
                                8.5 8.5 0 0 1-3.7-.8L3 20l1.3-4.2
                                A8.4 8.4 0 1 1 21 11.5Z" />

                            <path d="M8 12h.01M12 12h.01M16 12h.01" />
                        </svg>
                    </div>

                    <div>
                        <h2>Ask Your Data</h2>

                        <p>
                            Ask a question in natural language and let AI
                            analyze your dataset.
                        </p>
                    </div>

                </div>

                <div class="ai-badge">
                    <span>✦</span>
                    AI Powered
                </div>

            </div>


            <!-- Question -->

            <div class="question-area">

                <label for="question">
                    What do you want to know?
                </label>

                <div class="textarea-wrapper">

                    <textarea id="question" v-model="question" rows="4"
                        placeholder="Example: Show me the top 5 stores by average weekly sales during holidays."
                        :disabled="loading" @keydown.ctrl.enter="analyze"></textarea>

                    <div class="textarea-icon">
                        ✦
                    </div>

                </div>

                <div class="question-footer">

                    <span class="shortcut">
                        Press
                        <kbd>Ctrl</kbd>
                        +
                        <kbd>Enter</kbd>
                        to analyze
                    </span>

                    <button class="analyze-button" :disabled="loading || !question.trim()" @click="analyze">

                        <span v-if="loading" class="button-loader"></span>

                        <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />

                            <path d="M19 16v5M21.5 18.5h-5" />
                        </svg>

                        <span>
                            {{
                                loading
                                    ? "Analyzing..."
                                    : "Analyze Data"
                            }}
                        </span>

                        <span v-if="!loading" class="button-arrow">
                            →
                        </span>

                    </button>

                </div>

            </div>

        </div>


        <!-- =========================
             Error
        ========================== -->

        <div v-if="error" class="error-card">

            <div class="error-icon">
                !
            </div>

            <div class="error-content">

                <strong>
                    Analysis failed
                </strong>

                <p>
                    {{ error }}
                </p>

            </div>

        </div>


        <!-- =========================
             Result
        ========================== -->

        <div v-if="result" class="result-section">

            <div class="result-header">

                <div class="result-title">

                    <div class="result-icon">
                        ✓
                    </div>

                    <div>

                        <span class="result-label">
                            Analysis Result
                        </span>

                        <h3>
                            {{ result.visualization?.title }}
                        </h3>

                        <p>
                            {{ result.data.row_count }}
                            results returned.
                        </p>

                    </div>

                </div>

                <div class="result-status">
                    Analysis Complete
                </div>

            </div>


            <!-- Chart -->

            <div v-if="
                result.visualization &&
                result.visualization.type !== 'table'
            " class="chart-container">

                <AnalyticsChart :result="result" />

            </div>


            <!-- Table -->

            <div v-if="
                result.visualization?.type === 'table'
            " class="table-container">

                <div class="table-header">

                    <div>
                        <h4>Results</h4>

                        <p>
                            Data returned from your query
                        </p>
                    </div>

                    <span class="row-count">
                        {{ result.data.row_count }} rows
                    </span>

                </div>


                <div class="table-wrapper">

                    <table>

                        <thead>

                            <tr>

                                <th v-for="column in result.data.columns" :key="column">
                                    {{ column }}
                                </th>

                            </tr>

                        </thead>

                        <tbody>

                            <tr v-for="(row, index) in result.data.rows" :key="index">

                                <td v-for="column in result.data.columns" :key="column">
                                    {{ row[column] }}
                                </td>

                            </tr>

                        </tbody>

                    </table>

                </div>

            </div>

        </div>

    </section>
</template>


<style scoped>
/* =========================
   Main
========================= */

.analytics-builder {
    width: 100%;
}


/* =========================
   Analytics Card
========================= */

.analytics-card {
    padding: 28px;

    border: 1px solid #e7e5f2;

    border-radius: 22px;

    background:
        linear-gradient(145deg,
            rgba(255, 255, 255, 0.98),
            rgba(249, 247, 255, 0.96));

    box-shadow:
        0 5px 15px rgba(15, 23, 42, 0.03),
        0 18px 45px rgba(79, 70, 229, 0.06);
}


/* =========================
   Header
========================= */

.section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;

    gap: 20px;

    margin-bottom: 26px;
}

.section-title {
    display: flex;
    align-items: center;

    gap: 13px;
}

.section-icon {
    width: 42px;
    height: 42px;

    display: flex;
    align-items: center;
    justify-content: center;

    border-radius: 12px;

    color: #6d28d9;

    background:
        linear-gradient(135deg,
            #ede9fe,
            #e0e7ff);
}

.section-icon svg {
    width: 22px;
    height: 22px;
}

.section-title h2 {
    margin: 0;

    color: #172033;

    font-size: 21px;
    font-weight: 750;

    letter-spacing: -0.4px;
}

.section-title p {
    margin: 4px 0 0;

    color: #7a8496;

    font-size: 13px;

    line-height: 1.5;
}


/* =========================
   AI Badge
========================= */

.ai-badge {
    display: flex;
    align-items: center;

    gap: 6px;

    padding: 7px 11px;

    border-radius: 999px;

    background: #f3efff;

    color: #6d28d9;

    font-size: 12px;
    font-weight: 650;

    white-space: nowrap;
}

.ai-badge span {
    font-size: 14px;
}


/* =========================
   Question
========================= */

.question-area {
    display: flex;
    flex-direction: column;

    gap: 9px;
}

.question-area label {
    color: #344054;

    font-size: 13px;
    font-weight: 650;
}


/* =========================
   Textarea
========================= */

.textarea-wrapper {
    position: relative;
}

.textarea-wrapper textarea {
    width: 100%;

    min-height: 130px;

    padding: 17px 48px 17px 17px;

    border: 1px solid #d9d6e8;

    border-radius: 15px;

    background: #ffffff;

    color: #172033;

    font-family: inherit;

    font-size: 14px;

    line-height: 1.6;

    resize: vertical;

    box-sizing: border-box;

    transition:
        border-color 0.2s ease,
        box-shadow 0.2s ease;
}

.textarea-wrapper textarea::placeholder {
    color: #a1a8b5;
}

.textarea-wrapper textarea:focus {
    outline: none;

    border-color: #8b5cf6;

    box-shadow:
        0 0 0 4px rgba(139, 92, 246, 0.10);
}

.textarea-wrapper textarea:disabled {
    cursor: wait;

    background: #f8f9fc;
}


/* AI sparkle */

.textarea-icon {
    position: absolute;

    right: 16px;
    bottom: 16px;

    color: #7c3aed;

    font-size: 20px;

    pointer-events: none;
}


/* =========================
   Question Footer
========================= */

.question-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;

    gap: 15px;

    margin-top: 5px;
}

.shortcut {
    color: #98a2b3;

    font-size: 11px;
}

kbd {
    display: inline-block;

    padding: 2px 5px;

    margin: 0 2px;

    border: 1px solid #d9dce5;

    border-bottom-width: 2px;

    border-radius: 5px;

    background: #ffffff;

    color: #667085;

    font-size: 10px;

    font-family: inherit;
}


/* =========================
   Analyze Button
========================= */

.analyze-button {
    display: flex;
    align-items: center;

    gap: 9px;

    min-width: 155px;

    padding: 12px 17px;

    border: none;

    border-radius: 11px;

    background:
        linear-gradient(135deg,
            #7c3aed,
            #6366f1);

    color: #ffffff;

    font-size: 13px;
    font-weight: 700;

    cursor: pointer;

    box-shadow:
        0 8px 18px rgba(99, 102, 241, 0.24);

    transition:
        transform 0.2s ease,
        box-shadow 0.2s ease,
        opacity 0.2s ease;
}

.analyze-button:hover:not(:disabled) {
    transform: translateY(-2px);

    box-shadow:
        0 12px 24px rgba(99, 102, 241, 0.3);
}

.analyze-button:active:not(:disabled) {
    transform: translateY(0);
}

.analyze-button:disabled {
    cursor: not-allowed;

    opacity: 0.55;

    box-shadow: none;
}

.analyze-button svg {
    width: 18px;
    height: 18px;
}

.button-arrow {
    margin-left: auto;

    font-size: 17px;
}


/* Loading */

.button-loader {
    width: 15px;
    height: 15px;

    border: 2px solid rgba(255, 255, 255, 0.4);

    border-top-color: #ffffff;

    border-radius: 50%;

    animation: spin 0.7s linear infinite;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}


/* =========================
   Error
========================= */

.error-card {
    display: flex;
    align-items: center;

    gap: 13px;

    margin-top: 18px;

    padding: 16px 18px;

    border: 1px solid #fecaca;

    border-radius: 14px;

    background: #fffafa;
}

.error-icon {
    width: 34px;
    height: 34px;

    display: flex;
    align-items: center;
    justify-content: center;

    flex-shrink: 0;

    border-radius: 50%;

    background: #fee2e2;

    color: #dc2626;

    font-weight: 750;
}

.error-content strong {
    display: block;

    margin-bottom: 3px;

    color: #991b1b;

    font-size: 13px;
}

.error-content p {
    margin: 0;

    color: #b42318;

    font-size: 12px;
}


/* =========================
   Results
========================= */

.result-section {
    margin-top: 24px;

    padding: 24px;

    border: 1px solid #e7e5f2;

    border-radius: 20px;

    background: #ffffff;

    box-shadow:
        0 5px 18px rgba(15, 23, 42, 0.04);
}


/* Result Header */

.result-header {
    display: flex;
    align-items: center;
    justify-content: space-between;

    gap: 20px;

    margin-bottom: 22px;
}

.result-title {
    display: flex;
    align-items: flex-start;

    gap: 12px;
}

.result-icon {
    width: 38px;
    height: 38px;

    display: flex;
    align-items: center;
    justify-content: center;

    flex-shrink: 0;

    border-radius: 11px;

    background: #ecfdf5;

    color: #059669;

    font-size: 18px;
    font-weight: 750;
}

.result-label {
    display: block;

    margin-bottom: 3px;

    color: #7a8496;

    font-size: 11px;
    font-weight: 650;

    text-transform: uppercase;

    letter-spacing: 0.5px;
}

.result-header h3 {
    margin: 0;

    color: #172033;

    font-size: 19px;
    font-weight: 700;
}

.result-header p {
    margin: 4px 0 0;

    color: #98a2b3;

    font-size: 12px;
}

.result-status {
    padding: 7px 11px;

    border-radius: 999px;

    background: #ecfdf5;

    color: #047857;

    font-size: 11px;
    font-weight: 650;

    white-space: nowrap;
}


/* =========================
   Chart
========================= */

.chart-container {
    width: 100%;

    padding: 18px;

    border: 1px solid #edf0f5;

    border-radius: 14px;

    background: #fcfcfe;
}


/* =========================
   Table
========================= */

.table-container {
    overflow: hidden;

    border: 1px solid #e8eaf1;

    border-radius: 14px;

    background: #ffffff;
}

.table-header {
    display: flex;
    align-items: center;
    justify-content: space-between;

    gap: 15px;

    padding: 16px 18px;

    border-bottom: 1px solid #edf0f5;
}

.table-header h4 {
    margin: 0;

    color: #172033;

    font-size: 14px;
    font-weight: 700;
}

.table-header p {
    margin: 3px 0 0;

    color: #98a2b3;

    font-size: 11px;
}

.row-count {
    padding: 5px 9px;

    border-radius: 7px;

    background: #f5f3ff;

    color: #6d28d9;

    font-size: 11px;
    font-weight: 650;
}

.table-wrapper {
    width: 100%;

    overflow-x: auto;
}

table {
    width: 100%;

    min-width: 600px;

    border-collapse: collapse;
}

th,
td {
    padding: 13px 16px;

    text-align: left;

    border-bottom: 1px solid #edf0f5;

    white-space: nowrap;
}

th {
    background: #f8f9fc;

    color: #667085;

    font-size: 11px;
    font-weight: 700;

    text-transform: uppercase;

    letter-spacing: 0.35px;
}

td {
    color: #475467;

    font-size: 12px;
}

tbody tr {
    transition: background 0.15s ease;
}

tbody tr:hover {
    background: #faf9ff;
}

tbody tr:last-child td {
    border-bottom: none;
}


/* =========================
   Responsive
========================= */

@media (max-width: 700px) {

    .analytics-card,
    .result-section {
        padding: 20px;
    }

    .section-header,
    .result-header {
        align-items: flex-start;

        flex-direction: column;
    }

    .ai-badge,
    .result-status {
        align-self: flex-start;
    }

    .question-footer {
        align-items: flex-start;

        flex-direction: column;
    }

    .analyze-button {
        width: 100%;

        justify-content: center;
    }

    .result-section {
        margin-top: 18px;
    }
}
</style>