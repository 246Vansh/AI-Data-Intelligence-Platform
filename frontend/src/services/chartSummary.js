// =========================================================
// CHART DATA + METRIC SUMMARY (pure)
// =========================================================
//
// Extracted unchanged from AnalyticsChart.vue (workspace Phase 2) so the
// chart and the result header's KPI row compute from ONE implementation
// - no second copy of the maths to drift. No Vue, no DOM: tested with
// node --test (chartSummary.test.js).
//
// Nothing here aggregates raw data: every row is already one group's
// aggregate as returned by the backend.

export const SUPPORTED_CHART_TYPES = Object.freeze(["bar", "line", "pie", "scatter"]);

function isBlank(value) {
    return value === null || value === undefined || value === "";
}

// X-axis labels: a missing category is shown as "Unknown".
export function extractCategories(rows, xColumn) {
    return rows.map((row) => {
        const value = row?.[xColumn];
        return isBlank(value) ? "Unknown" : String(value);
    });
}

// Y values: a missing or non-numeric aggregate is null (never 0).
export function extractNumericValues(rows, yColumn) {
    return rows.map((row) => {
        const value = row?.[yColumn];
        if (isBlank(value)) {
            return null;
        }
        const number = Number(value);
        return Number.isFinite(number) ? number : null;
    });
}

export function validValues(numericValues) {
    return numericValues.filter((value) => value !== null && Number.isFinite(value));
}

// Everything the chart and the KPI row need from one /api/analyze result.
export function summarizeResult(result) {
    const rows = Array.isArray(result?.data?.rows) ? result.data.rows : [];
    const visualization = result?.visualization || null;
    const visualizationType = visualization?.type || null;
    const encoding = visualization?.encoding || {};
    const xColumn = encoding?.x || null;
    const yColumn = encoding?.y || null;

    const hasChartData =
        rows.length > 0 &&
        !!visualization &&
        !!xColumn &&
        !!yColumn &&
        SUPPORTED_CHART_TYPES.includes(visualizationType);

    const numericValues = extractNumericValues(rows, yColumn);
    const valid = validValues(numericValues);

    // Each value is already one group's aggregate. Adding them up is only
    // a dataset total for additive aggregations, and only when no groups
    // were cut off by the row limit; for mean/median/min/max a "Total" of
    // group values has no meaning.
    const aggregation = result?.plan?.aggregation || null;
    const rowLimitReached = result?.data?.row_limit_reached === true;
    const isAdditive = ["sum", "count"].includes(aggregation);
    const totalLabel = isAdditive ? (rowLimitReached ? "Total (shown)" : "Total") : null;

    const metric = result?.plan?.metric;
    const metricLabel = aggregation && metric ? `${aggregation} of ${metric}` : yColumn;

    const totalValue = valid.reduce((sum, value) => sum + value, 0);

    return {
        rows,
        visualization,
        visualizationType,
        xColumn,
        yColumn,
        hasChartData,
        numericValues,
        validNumericValues: valid,
        aggregation,
        rowLimitReached,
        totalLabel,
        metricLabel,
        totalValue,
        averageValue: valid.length ? totalValue / valid.length : null,
        minimumValue: valid.length ? Math.min(...valid) : null,
        maximumValue: valid.length ? Math.max(...valid) : null,
        // The KPI strip is shown exactly when the old chart summary strip
        // was: chartable data, not a pie, at least one numeric value.
        showKpis: hasChartData && visualizationType !== "pie" && valid.length > 0,
    };
}

// =========================================================
// FORMATTERS (unchanged from AnalyticsChart.vue)
// =========================================================

export function formatNumber(value) {
    if (isBlank(value)) {
        return "—";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return String(value);
    }
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(number);
}

export function formatCompactNumber(value) {
    if (isBlank(value)) {
        return "—";
    }
    const number = Number(value);
    if (!Number.isFinite(number)) {
        return String(value);
    }
    return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(number);
}
