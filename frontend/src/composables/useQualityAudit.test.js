// Run with: node --test src/composables/useQualityAudit.test.js
// Built-in node:test - no test framework dependency.
import test from "node:test";
import assert from "node:assert/strict";
import { effectScope, nextTick, ref } from "vue";

import { useQualityAudit } from "./useQualityAudit.js";

// A fake getDatasetQuality: records every call; each call's promise is
// settled by the test (resolve / reject), so timing is explicit.
function fakeFetch() {
    const calls = [];
    const fetchQuality = (datasetId, options) =>
        new Promise((resolve, reject) => {
            calls.push({ datasetId, options, resolve, reject });
        });
    return { calls, fetchQuality };
}

function setup({ datasetId = "ds-1", active = false } = {}) {
    const id = ref(datasetId);
    const isActive = ref(active);
    const fake = fakeFetch();
    const scope = effectScope();
    const audit = scope.run(() =>
        useQualityAudit({
            datasetId: id,
            active: isActive,
            fetchQuality: fake.fetchQuality,
            errorMessage: (err) => `message: ${err.message}`,
        }),
    );
    return { id, isActive, audit, calls: fake.calls, stop: () => scope.stop() };
}

const AUDIT = { status: "warning", issue_count: 1, issues: [{ severity: "warning" }] };

test("selecting a dataset while Quality is inactive requests nothing", async () => {
    const { id, calls, audit, stop } = setup({ active: false });

    id.value = "ds-2";
    await nextTick();

    assert.equal(calls.length, 0);
    assert.equal(audit.loading.value, false);
    assert.equal(audit.data.value, null);
    stop();
});

test("first activation of Quality requests the audit exactly once, from the cache path", async () => {
    const { isActive, calls, audit, stop } = setup({ active: false });

    isActive.value = true;
    await nextTick();

    assert.equal(calls.length, 1);
    assert.equal(calls[0].datasetId, "ds-1");
    assert.deepEqual(calls[0].options, { force: false });
    assert.equal(audit.loading.value, true);

    calls[0].resolve(AUDIT);
    await nextTick();

    assert.deepEqual(audit.data.value, AUDIT);
    assert.equal(audit.loading.value, false);
    stop();
});

test("opening on Quality directly (tab already active at mount) requests once", () => {
    const { calls, stop } = setup({ active: true });

    assert.equal(calls.length, 1);
    stop();
});

test("leaving Quality and returning reuses the loaded result (no new request)", async () => {
    const { isActive, calls, audit, stop } = setup({ active: true });
    calls[0].resolve(AUDIT);
    await nextTick();

    for (let i = 0; i < 3; i += 1) {
        isActive.value = false;
        await nextTick();
        isActive.value = true;
        await nextTick();
    }

    assert.equal(calls.length, 1);
    assert.deepEqual(audit.data.value, AUDIT);
    stop();
});

test("leaving and returning while the first request is still running does not send another", async () => {
    const { isActive, calls, stop } = setup({ active: true });

    isActive.value = false;
    await nextTick();
    isActive.value = true;
    await nextTick();

    assert.equal(calls.length, 1);
    stop();
});

test("Refresh is the only re-request, and it bypasses the browser cache", async () => {
    const { calls, audit, stop } = setup({ active: true });
    calls[0].resolve(AUDIT);
    await nextTick();

    const refreshed = audit.refresh();

    assert.equal(calls.length, 2);
    assert.deepEqual(calls[1].options, { force: true });
    assert.equal(audit.loading.value, true);

    const newer = { ...AUDIT, issue_count: 2 };
    calls[1].resolve(newer);
    await refreshed;

    assert.deepEqual(audit.data.value, newer);
    assert.equal(audit.loading.value, false);
    stop();
});

test("an error is shown, and Refresh is the retry", async () => {
    const { calls, audit, stop } = setup({ active: true });

    calls[0].reject(new Error("boom"));
    await nextTick();
    await nextTick();

    assert.equal(audit.error.value, "message: boom");
    assert.equal(audit.loading.value, false);
    assert.equal(audit.data.value, null);

    const retried = audit.refresh();
    assert.equal(audit.error.value, null);
    calls[1].resolve(AUDIT);
    await retried;

    assert.deepEqual(audit.data.value, AUDIT);
    assert.equal(audit.error.value, null);
    stop();
});

test("switching dataset forgets the old audit; the new one is requested only once Quality is active", async () => {
    const { id, isActive, calls, audit, stop } = setup({ active: true });
    calls[0].resolve(AUDIT);
    await nextTick();

    isActive.value = false;
    id.value = "ds-2";
    await nextTick();

    assert.equal(calls.length, 1);
    assert.equal(audit.data.value, null);

    isActive.value = true;
    await nextTick();

    assert.equal(calls.length, 2);
    assert.equal(calls[1].datasetId, "ds-2");
    stop();
});

test("a late response for the previous dataset is ignored", async () => {
    const { id, calls, audit, stop } = setup({ active: true });

    id.value = "ds-2";
    await nextTick();
    assert.equal(calls.length, 2);

    calls[0].resolve({ ...AUDIT, status: "stale" });
    calls[1].resolve(AUDIT);
    await nextTick();
    await nextTick();

    assert.deepEqual(audit.data.value, AUDIT);
    stop();
});

test("no dataset selected: nothing is requested even when Quality is active", async () => {
    const { calls, audit, stop } = setup({ datasetId: "", active: true });
    await nextTick();

    assert.equal(calls.length, 0);
    assert.equal(audit.loading.value, false);
    stop();
});
