// Run with: node --test src/services/chartSummary.test.js
// Pins the extracted chart/KPI maths to the behaviour it had inside
// AnalyticsChart.vue: NULL aggregates excluded (never zero), Total only
// for additive aggregations, "(shown)" when the row limit cut groups off.
import test from "node:test";
import assert from "node:assert/strict";

import {
    extractCategories,
    extractNumericValues,
    formatCompactNumber,
    formatNumber,
    summarizeResult,
} from "./chartSummary.js";

const result = (overrides = {}) => ({
    plan: { metric: "revenue", aggregation: "sum" },
    visualization: { type: "bar", title: "Revenue by region", encoding: { x: "region", y: "sum_revenue" } },
    data: {
        rows: [
            { region: "North", sum_revenue: 1200.5 },
            { region: "South", sum_revenue: 800 },
            { region: null, sum_revenue: null },
        ],
        row_limit_reached: false,
    },
    ...overrides,
});

test("missing categories become 'Unknown'; missing/non-numeric values become null", () => {
    assert.deepEqual(extractCategories([{ x: "a" }, { x: null }, { x: "" }, {}], "x"), ["a", "Unknown", "Unknown", "Unknown"]);
    assert.deepEqual(extractNumericValues([{ y: 1 }, { y: "2" }, { y: null }, { y: "" }, { y: "abc" }], "y"), [1, 2, null, null, null]);
});

test("sum aggregation: Total of returned groups; NULL group excluded from values", () => {
    const s = summarizeResult(result());
    assert.equal(s.hasChartData, true);
    assert.equal(s.totalLabel, "Total");
    assert.equal(s.totalValue, 2000.5);
    assert.equal(s.validNumericValues.length, 2);
    assert.equal(s.rows.length, 3);
    assert.equal(s.averageValue, 1000.25);
    assert.equal(s.minimumValue, 800);
    assert.equal(s.maximumValue, 1200.5);
    assert.equal(s.metricLabel, "sum of revenue");
    assert.equal(s.showKpis, true);
});

test("row limit reached -> 'Total (shown)'", () => {
    const s = summarizeResult(result({ data: { ...result().data, row_limit_reached: true } }));
    assert.equal(s.totalLabel, "Total (shown)");
});

test("non-additive aggregation has no Total (UI shows group count instead)", () => {
    for (const aggregation of ["mean", "median", "min", "max"]) {
        assert.equal(summarizeResult(result({ plan: { metric: "revenue", aggregation } })).totalLabel, null, aggregation);
    }
    assert.equal(summarizeResult(result({ plan: { metric: "revenue", aggregation: "count" } })).totalLabel, "Total");
});

test("KPIs only for chartable, non-pie results with numeric values (same rule as the old strip)", () => {
    assert.equal(summarizeResult(result({ visualization: { type: "pie", encoding: { x: "region", y: "sum_revenue" } } })).showKpis, false);
    assert.equal(summarizeResult(result({ visualization: { type: "table", encoding: { x: "region", y: "sum_revenue" } } })).showKpis, false);
    assert.equal(summarizeResult(result({ data: { rows: [] } })).showKpis, false);
    assert.equal(summarizeResult(result({ data: { rows: [{ region: "A", sum_revenue: null }] } })).showKpis, false);
    assert.equal(summarizeResult(null).hasChartData, false);
});

test("metric label falls back to the y column", () => {
    assert.equal(summarizeResult(result({ plan: {} })).metricLabel, "sum_revenue");
});

test("formatters unchanged", () => {
    assert.equal(formatNumber(1234.567), "1,234.57");
    assert.equal(formatNumber(null), "—");
    assert.equal(formatNumber("abc"), "abc");
    assert.equal(formatCompactNumber(2000.5), "2K");
    assert.equal(formatCompactNumber(1250000), "1.3M");
    assert.equal(formatCompactNumber(""), "—");
});
