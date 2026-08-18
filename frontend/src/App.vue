<script setup>
import DatasetOverview from "./components/DatasetOverview.vue";
import AnalyticsBuilder from "./components/AnalyticsBuilder.vue";
import DataPreview from "./components/DataPreview.vue";
</script>

<template>
  <div class="app">
    <header class="app-header">
      <div class="container">
        <div class="brand">
          <div class="brand-icon">✦</div>

          <div>
            <h1>AI Data Intelligence Platform</h1>
            <p>Interactive data analytics dashboard</p>
          </div>
        </div>

        <div class="status">
          <span class="status-dot"></span>
          Dataset Loaded
        </div>
      </div>
    </header>

    <main class="container main-content">
      <section class="hero">
        <div>
          <h2>AI Data Intelligence Platform</h2>
          <p>
            Explore your dataset, understand its structure, and ask questions
            using natural language.
          </p>
        </div>

        <div class="hero-visual">
          <div class="chart-bar bar-1"></div>
          <div class="chart-bar bar-2"></div>
          <div class="chart-bar bar-3"></div>
          <div class="chart-bar bar-4"></div>
        </div>
      </section>

      <DatasetOverview />
      <DataPreview/>

      <section class="analytics-section">
        <AnalyticsBuilder />
      </section>
    </main>
  </div>
</template>

<style>
* {
  box-sizing: border-box;
}

body {
  margin: 0;
  font-family:
    Inter,
    -apple-system,
    BlinkMacSystemFont,
    "Segoe UI",
    sans-serif;
  background: #f8f9ff;
  color: #172033;
}

button,
input,
textarea {
  font: inherit;
}

.app {
  min-height: 100vh;
  background:
    radial-gradient(circle at 85% 10%,
      rgba(124, 58, 237, 0.08),
      transparent 30%),
    #f8f9ff;
}

.container {
  width: min(1400px, calc(100% - 64px));
  margin: 0 auto;
}

/* Header */

.app-header {
  background: rgba(255, 255, 255, 0.9);
  border-bottom: 1px solid #e8eaf0;
  backdrop-filter: blur(12px);
}

.app-header .container {
  min-height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.brand-icon {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(135deg, #7c3aed, #4f46e5);
  color: white;
  font-size: 22px;
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.25);
}

.brand h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #172033;
}

.brand p {
  margin: 3px 0 0;
  font-size: 13px;
  color: #697386;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 999px;
  background: #ecfdf5;
  color: #047857;
  font-size: 13px;
  font-weight: 600;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #10b981;
}

/* Main */

.main-content {
  padding-top: 44px;
  padding-bottom: 60px;
}

/* Hero */

.hero {
  min-height: 220px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 40px;
  margin-bottom: 34px;
}

.hero h2 {
  margin: 0;
  font-size: clamp(36px, 4vw, 58px);
  line-height: 1.05;
  letter-spacing: -1.8px;
  color: #111827;
}

.hero p {
  max-width: 650px;
  margin: 16px 0 0;
  font-size: 17px;
  line-height: 1.6;
  color: #667085;
}

.hero-visual {
  width: 220px;
  height: 150px;
  display: flex;
  align-items: end;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  border-radius: 24px;
  background: linear-gradient(145deg,
      rgba(124, 58, 237, 0.12),
      rgba(59, 130, 246, 0.08));
  border: 1px solid rgba(124, 58, 237, 0.1);
}

.chart-bar {
  width: 28px;
  border-radius: 8px 8px 3px 3px;
  background: linear-gradient(180deg, #8b5cf6, #6366f1);
}

.bar-1 {
  height: 45px;
}

.bar-2 {
  height: 75px;
}

.bar-3 {
  height: 100px;
}

.bar-4 {
  height: 125px;
}

/* Analytics */

.analytics-section {
  margin-top: 40px;
}

/* Responsive */

@media (max-width: 900px) {
  .container {
    width: min(100% - 32px, 700px);
  }

  .hero {
    min-height: auto;
  }

  .hero-visual {
    display: none;
  }
}

@media (max-width: 600px) {
  .app-header .container {
    min-height: 68px;
  }

  .status {
    display: none;
  }

  .main-content {
    padding-top: 28px;
  }

  .hero h2 {
    font-size: 36px;
  }

  .hero p {
    font-size: 15px;
  }
}
</style>