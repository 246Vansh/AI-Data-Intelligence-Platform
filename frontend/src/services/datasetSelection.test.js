// Run with: node --test src/services/datasetSelection.test.js
import test from "node:test";
import assert from "node:assert/strict";

import { pickInitialDatasetId } from "./datasetSelection.js";

test("approved policy: nothing is selected automatically after a reload", () => {
    assert.equal(pickInitialDatasetId([]), "");
    assert.equal(pickInitialDatasetId(null), "");
    assert.equal(pickInitialDatasetId([{ dataset_id: "only-one", created_at: "2026-01-01T00:00:00Z" }]), "");
    assert.equal(pickInitialDatasetId([{ dataset_id: "a" }, { dataset_id: "b" }]), "");
});
