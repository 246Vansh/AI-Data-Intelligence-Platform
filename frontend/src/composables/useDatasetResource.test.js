// Run with: node --test src/composables/useDatasetResource.test.js
// Built-in node:test - no test framework dependency.
import test from "node:test";
import assert from "node:assert/strict";
import { effectScope, nextTick, ref } from "vue";

import { useDatasetResource } from "./useDatasetResource.js";

function setup({ datasetId = "ds-1", active = false } = {}) {
    const id = ref(datasetId);
    const isActive = ref(active);
    const calls = [];
    const fetch = (dataset, options) =>
        new Promise((resolve, reject) => {
            calls.push({ dataset, options, resolve, reject });
        });
    const scope = effectScope();
    const resource = scope.run(() =>
        useDatasetResource({
            datasetId: id,
            active: isActive,
            fetch,
            errorMessage: (err) => `message: ${err.message}`,
        }),
    );
    return { id, isActive, calls, resource, stop: () => scope.stop() };
}

async function flush() {
    await nextTick();
    await nextTick();
}

test("inactive: nothing requested, nothing settled", async () => {
    const { id, calls, resource, stop } = setup({ active: false });
    id.value = "ds-2";
    await flush();

    assert.equal(calls.length, 0);
    assert.equal(resource.loading.value, false);
    assert.equal(resource.settled.value, false);
    stop();
});

test("active at creation (e.g. the app opened on that tab) requests immediately, once", () => {
    const { calls, resource, stop } = setup({ active: true });

    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].options, { force: false });
    assert.equal(resource.loading.value, true);
    stop();
});

test("first load settles with data; leaving and returning sends nothing", async () => {
    const { isActive, calls, resource, stop } = setup({ active: true });
    calls[0].resolve({ rows: [1] });
    await flush();

    assert.deepEqual(resource.data.value, { rows: [1] });
    assert.equal(resource.settled.value, true);
    assert.equal(resource.loading.value, false);

    isActive.value = false;
    await flush();
    isActive.value = true;
    await flush();

    assert.equal(calls.length, 1);
    stop();
});

test("refresh keeps the data, sets refreshing (not loading) and forces", async () => {
    const { calls, resource, stop } = setup({ active: true });
    calls[0].resolve("old");
    await flush();

    const done = resource.refresh();
    assert.equal(resource.refreshing.value, true);
    assert.equal(resource.loading.value, false);
    assert.equal(resource.data.value, "old");
    assert.deepEqual(calls[1].options, { force: true });

    calls[1].resolve("new");
    await done;
    assert.equal(resource.data.value, "new");
    assert.equal(resource.refreshing.value, false);
    stop();
});

test("an error settles with a message; load() retries", async () => {
    const { calls, resource, stop } = setup({ active: true });
    calls[0].reject(new Error("boom"));
    await flush();

    assert.equal(resource.error.value, "message: boom");
    assert.equal(resource.settled.value, true);

    const retried = resource.load();
    assert.equal(resource.error.value, null);
    calls[1].resolve("ok");
    await retried;
    assert.equal(resource.data.value, "ok");
    stop();
});

test("dataset change resets state and ignores the old dataset's late response", async () => {
    const { id, isActive, calls, resource, stop } = setup({ active: true });

    isActive.value = false;
    id.value = "ds-2";
    await flush();

    assert.equal(resource.settled.value, false);
    assert.equal(resource.loading.value, false);

    calls[0].resolve("late for ds-1");
    await flush();
    assert.equal(resource.data.value, null);
    assert.equal(resource.settled.value, false);

    isActive.value = true;
    await flush();
    assert.equal(calls.length, 2);
    assert.equal(calls[1].dataset, "ds-2");
    stop();
});

test("no dataset: never requests, never loading", async () => {
    const { calls, resource, stop } = setup({ datasetId: "", active: true });
    await flush();

    assert.equal(calls.length, 0);
    assert.equal(resource.loading.value, false);
    stop();
});
