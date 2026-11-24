// Run with: node --test src/services/datasetCache.test.js
// Built-in node:test - no test framework dependency.
//
// The client-side dataset cache (api.js) as the demand-driven quality
// audit uses it, against the real axios instance with a fake adapter.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const { AxiosError } = await import("axios");
const apiModule = await import("./api.js");
const {
    api,
    clearDatasetCache,
    datasetUrls,
    evictDatasetCache,
    getCachedResponse,
    getDatasetMetadata,
    getDatasetPreview,
    getDatasetQuality,
} = apiModule;

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");

function respond(config, status, data) {
    const response = { status, statusText: String(status), data, headers: {}, config };
    if (status >= 200 && status < 300) {
        return Promise.resolve(response);
    }
    return Promise.reject(new AxiosError("Request failed", "ERR_BAD_REQUEST", config, {}, response));
}

// Installs an adapter for one test. Every request is recorded; each
// response is held until the test calls release(url[, status, data]).
async function withServer(fn) {
    const hits = [];
    const pending = [];
    const original = api.defaults.adapter;

    api.defaults.adapter = (config) =>
        new Promise((resolve, reject) => {
            hits.push(config.url);
            pending.push({ config, resolve, reject });
        });

    function release(url, status = 200, data = { url }) {
        const index = pending.findIndex((entry) => entry.config.url === url);
        assert.notEqual(index, -1, `no pending request for ${url}`);
        const [entry] = pending.splice(index, 1);
        respond(entry.config, status, data).then(entry.resolve, entry.reject);
    }

    clearDatasetCache();
    try {
        await fn({ hits, release });
    } finally {
        api.defaults.adapter = original;
        clearDatasetCache();
    }
}

const QUALITY_A = datasetUrls.quality("a");

// What Dashboard.selectDataset() does before every selection.
function selectDataset(datasetId) {
    evictDatasetCache(datasetId, { keepInFlight: true });
}

test("getCachedResponse never sends a request, cached or not", async () => {
    await withServer(async ({ hits, release }) => {
        assert.equal(getCachedResponse(QUALITY_A), undefined);
        assert.equal(hits.length, 0);

        const loading = getDatasetQuality("a");
        // In flight is not cached: the lookup neither returns nor joins it.
        assert.equal(getCachedResponse(QUALITY_A), undefined);
        assert.equal(hits.length, 1);

        release(QUALITY_A, 200, { status: "valid" });
        await loading;

        assert.deepEqual(getCachedResponse(QUALITY_A), { status: "valid" });
        assert.equal(hits.length, 1);
    });
});

test("a cached audit is reused without a new request", async () => {
    await withServer(async ({ hits, release }) => {
        const first = getDatasetQuality("a");
        release(QUALITY_A, 200, { status: "valid" });
        await first;

        assert.deepEqual(await getDatasetQuality("a"), { status: "valid" });
        assert.equal(hits.length, 1);
    });
});

test("Refresh (force) sends one new request, but still joins one in flight", async () => {
    await withServer(async ({ hits, release }) => {
        const first = getDatasetQuality("a");
        release(QUALITY_A);
        await first;

        const refreshed = getDatasetQuality("a", { force: true });
        const again = getDatasetQuality("a", { force: true });
        assert.equal(hits.length, 2);

        release(QUALITY_A, 200, { status: "warning" });
        assert.deepEqual(await refreshed, { status: "warning" });
        assert.deepEqual(await again, { status: "warning" });
    });
});

test("re-selecting a dataset (A -> B -> A) while its audit runs shares the in-flight request", async () => {
    await withServer(async ({ hits, release }) => {
        selectDataset("a");
        const first = getDatasetQuality("a");

        selectDataset("b");
        selectDataset("a");
        const second = getDatasetQuality("a");

        assert.equal(hits.filter((url) => url === QUALITY_A).length, 1);

        release(QUALITY_A, 200, { status: "valid" });
        assert.deepEqual(await first, { status: "valid" });
        assert.deepEqual(await second, { status: "valid" });
    });
});

test("re-selecting drops the dataset's cached responses (incl. the audit), so they are re-verified", async () => {
    await withServer(async ({ hits, release }) => {
        const metadata = getDatasetMetadata("a");
        const quality = getDatasetQuality("a");
        release(datasetUrls.metadata("a"));
        release(QUALITY_A, 200, { status: "valid" });
        await Promise.all([metadata, quality]);

        selectDataset("a");

        assert.equal(getCachedResponse(QUALITY_A), undefined);
        assert.equal(getCachedResponse(datasetUrls.metadata("a")), undefined);

        const reverify = getDatasetMetadata("a");
        assert.equal(hits.filter((url) => url === datasetUrls.metadata("a")).length, 2);
        release(datasetUrls.metadata("a"));
        await reverify;
    });
});

test("default eviction (deletion) still drops cached AND in-flight entries, only for that dataset", async () => {
    await withServer(async ({ hits, release }) => {
        const quality = getDatasetQuality("a");
        release(QUALITY_A);
        await quality;
        const otherDataset = getDatasetQuality("b");
        release(datasetUrls.quality("b"));
        await otherDataset;

        const running = getDatasetMetadata("a");
        evictDatasetCache("a");

        assert.equal(getCachedResponse(QUALITY_A), undefined);
        assert.notEqual(getCachedResponse(datasetUrls.quality("b")), undefined);

        // The in-flight metadata is no longer shared: a new call re-requests.
        const fresh = getDatasetMetadata("a");
        assert.equal(hits.filter((url) => url === datasetUrls.metadata("a")).length, 2);

        release(datasetUrls.metadata("a"));
        release(datasetUrls.metadata("a"));
        await Promise.all([running, fresh]);
    });
});

test("a 404 evicts every entry of the dataset, including its cached quality audit", async () => {
    await withServer(async ({ release }) => {
        const quality = getDatasetQuality("a");
        release(QUALITY_A, 200, { status: "valid" });
        await quality;
        assert.notEqual(getCachedResponse(QUALITY_A), undefined);

        const missing = [];
        const stop = apiModule.onDatasetMissing((id) => missing.push(id));
        const preview = getDatasetPreview("a");
        release("/dataset/a/preview", 404, { detail: "Dataset not found." });
        await assert.rejects(preview);
        stop();

        assert.deepEqual(missing, ["a"]);
        assert.equal(getCachedResponse(QUALITY_A), undefined);
    });
});

test("session loss (401) still clears the whole cache, including a cached audit", async () => {
    await withServer(async ({ release }) => {
        const quality = getDatasetQuality("a");
        release(QUALITY_A, 200, { status: "valid" });
        await quality;

        const metadata = getDatasetMetadata("a");
        release(datasetUrls.metadata("a"), 401, { detail: "Not authenticated." });
        await assert.rejects(metadata);

        assert.equal(getCachedResponse(QUALITY_A), undefined);
    });
});

test("the context bar never requests the quality audit itself", () => {
    const source = readFileSync(join(SRC, "components", "workspace", "ContextBar.vue"), "utf8");

    assert.doesNotMatch(source, /getDatasetQuality/);
    assert.match(source, /getCachedResponse\(datasetUrls\.quality\(/);
    assert.match(source, /Quality: Not audited/);
});

test("DataQuality requests on activation, not on mount, and Dashboard passes the active tab", () => {
    const quality = readFileSync(join(SRC, "components", "DataQuality.vue"), "utf8");
    const dashboard = readFileSync(join(SRC, "components", "Dashboard.vue"), "utf8");

    assert.doesNotMatch(quality, /onMounted|getDatasetQuality/);
    assert.match(quality, /useQualityAudit\(/);
    assert.match(dashboard, /<DataQuality[^>]*:active="workspaceTab === 'quality'"/s);
    assert.match(dashboard, /evictDatasetCache\(datasetId, \{ keepInFlight: true \}\)/);
});
