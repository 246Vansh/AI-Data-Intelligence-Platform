<script setup>
import { onMounted, ref } from "vue";

import {
    getDatasetProfile,
} from "../services/api";

const profile = ref(null);
const loading = ref(true);
const error = ref(null);

async function loadProfile() {
    try {
        loading.value = true;
        error.value = null;

        profile.value = await getDatasetProfile();

    } catch (err) {
        console.error(err);

        error.value = "Unable to load dataset profile.";

    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    loadProfile();
});
</script>

<template>
    <section class="dataset-overview">

        <!-- Section Header -->
        <div class="section-header">
            <div class="section-title">
                <div class="section-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="3" width="18" height="18" rx="3" />
                        <path d="M8 8h8M8 12h8M8 16h5" />
                    </svg>
                </div>

                <div>
                    <h2>Dataset Overview</h2>
                    <p>Summary of your loaded dataset</p>
                </div>
            </div>
        </div>

        <!-- Loading -->
        <div v-if="loading" class="state-card">
            <div class="loader"></div>

            <div>
                <strong>Loading dataset</strong>
                <p>Preparing your dataset statistics...</p>
            </div>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="state-card error-state">
            <div class="state-icon">
                !
            </div>

            <div>
                <strong>Unable to load dataset</strong>
                <p>{{ error }}</p>

                <button type="button" @click="loadProfile">
                    Try Again
                </button>
            </div>
        </div>

        <!-- Dataset Statistics -->
        <div v-else-if="profile" class="overview-grid">

            <!-- Rows -->
            <article class="stat-card rows-card">

                <div class="stat-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M7 3h10l4 4v14H7z" />
                        <path d="M7 7h14" />
                        <path d="M11 3v4" />
                        <path d="M11 11h6M11 15h6M11 19h4" />
                    </svg>
                </div>

                <div class="stat-content">
                    <span class="stat-label">
                        Rows
                    </span>

                    <strong class="stat-value">
                        {{ profile.rows.toLocaleString() }}
                    </strong>

                    <span class="stat-description">
                        Total records
                    </span>
                </div>

            </article>

            <!-- Columns -->
            <article class="stat-card columns-card">

                <div class="stat-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="4" width="18" height="16" rx="2" />
                        <path d="M3 10h18" />
                        <path d="M9 10v10" />
                    </svg>
                </div>

                <div class="stat-content">
                    <span class="stat-label">
                        Columns
                    </span>

                    <strong class="stat-value">
                        {{ profile.columns }}
                    </strong>

                    <span class="stat-description">
                        Total features
                    </span>
                </div>

            </article>

            <!-- Duplicates -->
            <article class="stat-card duplicates-card">

                <div class="stat-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M8 8h10a3 3 0 0 1 3 3v7a3 3 0 0 1-3 3H11a3 3 0 0 1-3-3z" />
                        <path d="M16 8V6a3 3 0 0 0-3-3H6a3 3 0 0 0-3 3v7a3 3 0 0 0 3 3h2" />
                    </svg>
                </div>

                <div class="stat-content">
                    <span class="stat-label">
                        Duplicates
                    </span>

                    <strong class="stat-value">
                        {{ profile.duplicate_rows }}
                    </strong>

                    <span class="stat-description">
                        Duplicate rows
                    </span>
                </div>

            </article>

            <!-- Memory -->
            <article class="stat-card memory-card">

                <div class="stat-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="6" y="6" width="12" height="12" rx="2" />
                        <path d="M9 1v5M15 1v5M9 18v5M15 18v5" />
                        <path d="M1 9h5M1 15h5M18 9h5M18 15h5" />
                    </svg>
                </div>

                <div class="stat-content">
                    <span class="stat-label">
                        Memory
                    </span>

                    <strong class="stat-value">
                        {{
                            (
                                profile.memory_usage_bytes /
                                1024 /
                                1024
                            ).toFixed(2)
                        }}
                        <small>MB</small>
                    </strong>

                    <span class="stat-description">
                        In memory
                    </span>
                </div>

            </article>

        </div>

    </section>
</template>

<style scoped>
.dataset-overview {
    width: 100%;
}

/* =========================
   Section Header
========================= */

.section-header {
    margin-bottom: 18px;
}

.section-title {
    display: flex;
    align-items: center;
    gap: 12px;
}

.section-icon {
    width: 38px;
    height: 38px;

    display: flex;
    align-items: center;
    justify-content: center;

    border-radius: 11px;

    color: #6d28d9;

    background: linear-gradient(135deg,
            #ede9fe,
            #e0e7ff);
}

.section-icon svg {
    width: 20px;
    height: 20px;
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
   Statistics Grid
========================= */

.overview-grid {
    display: grid;

    grid-template-columns:
        repeat(4, minmax(0, 1fr));

    gap: 20px;
}

/* =========================
   Stat Card
========================= */

.stat-card {
    position: relative;

    display: flex;
    align-items: flex-start;

    gap: 16px;

    min-height: 138px;

    padding: 24px;

    background: rgba(255, 255, 255, 0.92);

    border: 1px solid #e8eaf1;

    border-radius: 18px;

    box-shadow:
        0 4px 12px rgba(15, 23, 42, 0.03),
        0 12px 28px rgba(15, 23, 42, 0.04);

    transition:
        transform 0.2s ease,
        box-shadow 0.2s ease,
        border-color 0.2s ease;
}

.stat-card:hover {
    transform: translateY(-3px);

    border-color: #ddd6fe;

    box-shadow:
        0 8px 20px rgba(15, 23, 42, 0.06),
        0 18px 35px rgba(15, 23, 42, 0.07);
}

/* =========================
   Icons
========================= */

.stat-icon {
    flex-shrink: 0;

    width: 52px;
    height: 52px;

    display: flex;
    align-items: center;
    justify-content: center;

    border-radius: 15px;
}

.stat-icon svg {
    width: 25px;
    height: 25px;
}

/* Rows */

.rows-card .stat-icon {
    color: #6d28d9;
    background: #f1edff;
}

/* Columns */

.columns-card .stat-icon {
    color: #2563eb;
    background: #eff6ff;
}

/* Duplicates */

.duplicates-card .stat-icon {
    color: #059669;
    background: #ecfdf5;
}

/* Memory */

.memory-card .stat-icon {
    color: #ea580c;
    background: #fff7ed;
}

/* =========================
   Content
========================= */

.stat-content {
    min-width: 0;
}

.stat-label {
    display: block;

    margin-bottom: 5px;

    color: #667085;

    font-size: 14px;
    font-weight: 600;
}

.stat-value {
    display: block;

    color: #172033;

    font-size: 30px;
    line-height: 1.15;
    font-weight: 750;

    letter-spacing: -0.8px;
}

.stat-value small {
    font-size: 16px;
    font-weight: 600;

    color: #667085;

    letter-spacing: 0;
}

.stat-description {
    display: block;

    margin-top: 7px;

    color: #98a2b3;

    font-size: 12px;
}

/* =========================
   Loading / Error
========================= */

.state-card {
    display: flex;
    align-items: center;
    gap: 14px;

    padding: 22px 24px;

    background: #ffffff;

    border: 1px solid #e8eaf1;

    border-radius: 16px;

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

.loader {
    width: 28px;
    height: 28px;

    border: 3px solid #ede9fe;
    border-top-color: #7c3aed;

    border-radius: 50%;

    animation: spin 0.8s linear infinite;
}

@keyframes spin {
    to {
        transform: rotate(360deg);
    }
}

/* Error */

.error-state {
    border-color: #fecaca;
    background: #fffafa;
}

.state-icon {
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

    border: 0;
    border-radius: 8px;

    background: #7c3aed;
    color: white;

    font-size: 12px;
    font-weight: 600;

    cursor: pointer;

    transition: background 0.2s ease;
}

.error-state button:hover {
    background: #6d28d9;
}

/* =========================
   Responsive
========================= */

@media (max-width: 1100px) {
    .overview-grid {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 600px) {
    .overview-grid {
        grid-template-columns: 1fr;
    }

    .stat-card {
        min-height: 120px;
        padding: 20px;
    }

    .stat-value {
        font-size: 26px;
    }
}
</style>