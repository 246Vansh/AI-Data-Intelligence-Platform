// Run with: node --test src/lib/cn.test.js
import test from "node:test";
import assert from "node:assert/strict";

import { cn } from "./cn.js";

test("a later conflicting utility wins (the Phase 6 height bug)", () => {
    assert.equal(cn("h-9 px-3", "h-11"), "px-3 h-11");
});

test("design-token font sizes and colors are different groups", () => {
    // Misconfigured, tailwind-merge would read both as colors and drop one.
    assert.equal(cn("text-data text-ink"), "text-data text-ink");
    assert.equal(cn("text-caption text-ink-muted", "text-body"), "text-ink-muted text-body");
    assert.equal(cn("text-ink", "text-forest"), "text-forest");
});

test("named radius, shadow and easing tokens resolve within their groups", () => {
    assert.equal(cn("rounded-control", "rounded-panel"), "rounded-panel");
    assert.equal(cn("shadow-panel", "shadow-overlay"), "shadow-overlay");
    assert.equal(cn("rounded-panel shadow-panel"), "rounded-panel shadow-panel");
});

test("accepts every shape Vue allows for class", () => {
    assert.equal(cn("a", ["b", { c: true, d: false }], null, undefined, false, ""), "a b c");
});
