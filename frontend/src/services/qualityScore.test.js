// Run with: node --test src/services/qualityScore.test.js
import test from "node:test";
import assert from "node:assert/strict";

import { healthScore, scoreBand, severityCounts } from "./qualityScore.js";

test("score: 100 minus the per-severity penalty, as the Quality screen always computed", () => {
    assert.equal(healthScore({ issues: [] }), 100);
    assert.equal(healthScore({ issues: [{ severity: "info" }, { severity: "info" }, { severity: "info" }] }), 91);
    assert.equal(healthScore({ issues: [{ severity: "warning" }, { severity: "error" }] }), 65);
    assert.equal(healthScore({ issues: Array.from({ length: 5 }, () => ({ severity: "error" })) }), 0);
});

test("no audit (or no issues list) gives no score, never 100%", () => {
    assert.equal(healthScore(null), null);
    assert.equal(healthScore({ status: "healthy" }), null);
    assert.equal(scoreBand(null), "unknown");
});

test("bands follow the existing 80 / 60 thresholds", () => {
    assert.equal(scoreBand(92), "good");
    assert.equal(scoreBand(80), "good");
    assert.equal(scoreBand(65), "fair");
    assert.equal(scoreBand(40), "poor");
});

test("severity counts; unknown severities count as info", () => {
    assert.deepEqual(
        severityCounts({ issues: [{ severity: "error" }, { severity: "warning" }, { severity: "info" }, { severity: "odd" }] }),
        { total: 4, error: 1, warning: 1, info: 2 },
    );
});
