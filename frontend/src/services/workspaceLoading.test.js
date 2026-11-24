// Run with: node --test src/services/workspaceLoading.test.js
// Built-in node:test - no test framework dependency.
//
// Which requests the workspace sends, and when. The project has no
// component-test library, so each panel's loading is reproduced here
// with the SAME composables and api.js functions, wired the way the
// components wire them (the source checks at the bottom pin that
// wiring), against the real axios instance with a fake adapter that
// records every request.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { effectScope, nextTick, ref } from "vue";

const { AxiosError } = await import("axios");
const apiModule = await import("./api.js");
const { useDatasetResource } = await import("../composables/useDatasetResource.js");
const { useQualityAudit } = await import("../composables/useQualityAudit.js");
const { useSuggestionMetadata } = await import("../composables/useSuggestionMetadata.js");

const {
    analyzeDataset,
    api,
    clearDatasetCache,
    evictDatasetCache,
    getCachedResponse,
    getDatasetMetadata,
    getDatasetPreview,
    getDatasetQuality,
} = apiModule;

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (...parts) => readFileSync(join(SRC, ...parts), "utf8");

// ---------------------------------------------------------
// Fake server: records every request; each one is answered when the
// test releases it.
// ---------------------------------------------------------

function respond(config, status, data) {
    const response = { status, statusText: String(status), data, headers: {}, config };
    if (status >= 200 && status < 300) {
        return Promise.resolve(response);
    }
    return Promise.reject(new AxiosError("Request failed", "ERR_BAD_REQUEST", config, {}, response));
}

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

    const count = (url) => hits.filter((hit) => hit === url).length;

    clearDatasetCache();
    try {
        await fn({ hits, release, count });
    } finally {
        api.defaults.adapter = original;
        clearDatasetCache();
    }
}

// Lets every pending promise settle (axios answers through several
// promise hops), then Vue's watchers run.
async function flush() {
    await new Promise((resolve) => setImmediate(resolve));
    await nextTick();
}

// ---------------------------------------------------------
// The workspace's panels, wired as in the components.
// ---------------------------------------------------------

function mountWorkspace({ tab = "analyze", datasetId = "a" } = {}) {
    const state = {
        tab: ref(tab),
        datasetId: ref(datasetId),
        analysisMode: ref("single"),
    };
    const id = () => state.datasetId.value;
    const scope = effectScope();

    const panels = scope.run(() => ({
        // DataPreview (active = Data tab): preview + column metadata.
        preview: useDatasetResource({ datasetId: id, active: () => state.tab.value === "data", fetch: getDatasetPreview }),
        dataMetadata: useDatasetResource({ datasetId: id, active: () => state.tab.value === "data", fetch: getDatasetMetadata }),
        // DatasetMetadata (active = Schema tab).
        schema: useDatasetResource({ datasetId: id, active: () => state.tab.value === "schema", fetch: getDatasetMetadata }),
        // AnalyticsBuilder suggestions (the component's own composable).
        suggestions: useSuggestionMetadata({ datasetId: id, analysisMode: () => state.analysisMode.value }),
        // DataQuality (active = Quality tab).
        quality: useQualityAudit({ datasetId: id, active: () => state.tab.value === "quality" }),
    }));

    return { ...state, panels, unmount: () => scope.stop() };
}

const PREVIEW_A = "/dataset/a/preview";
const METADATA_A = "/dataset/a/metadata";
const QUALITY_A = "/dataset/a/quality";
const isProfile = (url) => /\/profile$/.test(url);

// =========================================================
// SELECTION AND TABS
// =========================================================

test("selecting a dataset on Analyze sends no request at all (no /profile, /preview, /metadata, /quality)", async () => {
    await withServer(async ({ hits }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();

        // The context bar reads the cache only.
        assert.equal(getCachedResponse(QUALITY_A), undefined);

        assert.deepEqual(hits, []);
        workspace.unmount();
    });
});

test("suggestion metadata: nothing on selection; Suggest questions sends exactly one request", async () => {
    await withServer(async ({ count, release }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();
        assert.equal(count(METADATA_A), 0);
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, true);

        workspace.panels.suggestions.requestSuggestions();
        await flush();
        assert.equal(count(METADATA_A), 1);
        assert.equal(workspace.panels.suggestions.loading.value, true);
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, false);

        release(METADATA_A, 200, { row_count: 2, columns: {} });
        await flush();
        assert.deepEqual(workspace.panels.suggestions.data.value, { row_count: 2, columns: {} });
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, false);
        workspace.unmount();
    });
});

test("repeated Suggest questions clicks never send a duplicate request", async () => {
    await withServer(async ({ count, release }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        for (let i = 0; i < 3; i += 1) {
            workspace.panels.suggestions.requestSuggestions();
            await flush();
        }
        assert.equal(count(METADATA_A), 1);

        release(METADATA_A, 200, { row_count: 2, columns: {} });
        await flush();
        workspace.panels.suggestions.requestSuggestions();
        await flush();
        assert.equal(count(METADATA_A), 1);
        workspace.unmount();
    });
});

test("metadata already cached by Data or Schema is reused for suggestions with no request", async () => {
    await withServer(async ({ count, release }) => {
        const cached = getDatasetMetadata("a");
        release(METADATA_A, 200, { row_count: 5, columns: {} });
        await cached;

        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();
        assert.equal(count(METADATA_A), 1); // only the one above
        assert.deepEqual(workspace.panels.suggestions.data.value, { row_count: 5, columns: {} });
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, false);
        workspace.unmount();
    });
});

test("metadata loaded later by the Data tab also fills the suggestions, with no extra request", async () => {
    await withServer(async ({ count, release }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, true);

        workspace.tab.value = "data";
        await flush();
        release(PREVIEW_A);
        release(METADATA_A, 200, { row_count: 7, columns: {} });
        await flush();

        assert.equal(count(METADATA_A), 1);
        assert.deepEqual(workspace.panels.suggestions.data.value, { row_count: 7, columns: {} });
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, false);
        workspace.unmount();
    });
});

test("a failed suggestion load shows the error; Suggest questions is offered again and retries", async () => {
    await withServer(async ({ count, release }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        workspace.panels.suggestions.requestSuggestions();
        await flush();
        release(METADATA_A, 500, { detail: "Metadata generation failed." });
        await flush();

        assert.ok(workspace.panels.suggestions.error.value);
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, true);

        workspace.panels.suggestions.requestSuggestions();
        await flush();
        assert.equal(count(METADATA_A), 2);
        assert.equal(workspace.panels.suggestions.error.value, null);

        release(METADATA_A, 200, { row_count: 1, columns: {} });
        await flush();
        assert.deepEqual(workspace.panels.suggestions.data.value, { row_count: 1, columns: {} });
        workspace.unmount();
    });
});

test("comparison mode never requests suggestion metadata (static suggestions) and offers no button", async () => {
    await withServer(async ({ hits }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        workspace.analysisMode.value = "comparison";
        await flush();
        assert.equal(workspace.panels.suggestions.showSuggestButton.value, false);
        workspace.panels.suggestions.requestSuggestions();
        await flush();

        assert.deepEqual(hits, []);
        workspace.unmount();
    });
});

test("submitting a question sends /analyze alone - it neither triggers nor waits for metadata", async () => {
    await withServer(async ({ release, hits }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();

        const answer = analyzeDataset("total revenue", "a");
        await flush();
        assert.deepEqual(hits, ["/analyze"]);
        release("/analyze", 200, { question: "total revenue" });
        assert.deepEqual(await answer, { question: "total revenue" });

        // With suggestions still loading, /analyze still answers first.
        workspace.panels.suggestions.requestSuggestions();
        await flush();
        const second = analyzeDataset("average revenue", "a");
        await flush();
        release("/analyze", 200, { question: "average revenue" });
        assert.deepEqual(await second, { question: "average revenue" });
        assert.equal(workspace.panels.suggestions.loading.value, true);

        release(METADATA_A);
        await flush();
        workspace.unmount();
    });
});

test("opening Data loads preview and metadata once each; Schema then reuses the metadata", async () => {
    await withServer(async ({ count, release, hits }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        await flush();

        workspace.tab.value = "data";
        await flush();
        assert.equal(count(PREVIEW_A), 1);
        assert.equal(count(METADATA_A), 1);

        release(PREVIEW_A, 200, { columns: ["x"], rows: [{ x: 1 }] });
        release(METADATA_A, 200, { row_count: 1, columns: { x: { missing_count: 0 } } });
        await flush();

        workspace.tab.value = "schema";
        await flush();
        assert.equal(count(METADATA_A), 1);
        assert.deepEqual(workspace.panels.schema.data.value, { row_count: 1, columns: { x: { missing_count: 0 } } });

        assert.ok(!hits.some(isProfile));
        workspace.unmount();
    });
});

test("opening Schema while Data's metadata is still in flight shares that request", async () => {
    await withServer(async ({ count, release }) => {
        const workspace = mountWorkspace({ tab: "data" });
        await flush();
        workspace.tab.value = "schema";
        await flush();

        assert.equal(count(METADATA_A), 1);
        release(METADATA_A, 200, { row_count: 3, columns: {} });
        release(PREVIEW_A);
        await flush();
        assert.deepEqual(workspace.panels.schema.data.value, { row_count: 3, columns: {} });
        workspace.unmount();
    });
});

test("opening the app directly on #data or #schema loads that tab's data immediately", async () => {
    await withServer(async ({ count }) => {
        const data = mountWorkspace({ tab: "data" });
        await flush();
        assert.equal(count(PREVIEW_A), 1);
        assert.equal(count(METADATA_A), 1);
        data.unmount();
    });

    await withServer(async ({ count }) => {
        const schema = mountWorkspace({ tab: "schema" });
        await flush();
        assert.equal(count(METADATA_A), 1);
        assert.equal(count(PREVIEW_A), 0);
        schema.unmount();
    });
});

test("switching between every tab repeatedly never duplicates a request, and never requests /profile", async () => {
    await withServer(async ({ hits, release }) => {
        const workspace = mountWorkspace({ tab: "analyze" });
        workspace.panels.suggestions.requestSuggestions();

        for (let round = 0; round < 3; round += 1) {
            for (const tab of ["data", "schema", "quality", "analyze"]) {
                workspace.tab.value = tab;
                await flush();
            }
            if (round === 0) {
                release(PREVIEW_A);
                release(METADATA_A, 200, { row_count: 1, columns: {} });
                release(QUALITY_A, 200, { status: "valid", issues: [] });
                await flush();
            }
        }

        assert.deepEqual([...hits].sort(), [METADATA_A, PREVIEW_A, QUALITY_A].sort());
        assert.ok(!hits.some(isProfile));
        workspace.unmount();
    });
});

// =========================================================
// DATASET CHANGES AND INVALIDATION
// =========================================================

test("a late response for the previously selected dataset is ignored", async () => {
    await withServer(async ({ release, count }) => {
        const workspace = mountWorkspace({ tab: "data" });
        await flush();

        workspace.datasetId.value = "b";
        await flush();
        assert.equal(count("/dataset/b/preview"), 1);

        release(PREVIEW_A, 200, { rows: ["stale a"] });
        release("/dataset/b/preview", 200, { rows: ["b"] });
        await flush();

        assert.deepEqual(workspace.panels.preview.data.value, { rows: ["b"] });
        release(METADATA_A);
        workspace.unmount();
    });
});

test("re-selecting a dataset (Dashboard's eviction) keeps in-flight requests shared", async () => {
    await withServer(async ({ count, release }) => {
        const first = mountWorkspace({ tab: "data" });
        await flush();

        // A -> B -> A: Dashboard evicts with keepInFlight and remounts.
        evictDatasetCache("b", { keepInFlight: true });
        evictDatasetCache("a", { keepInFlight: true });
        first.unmount();
        const second = mountWorkspace({ tab: "data" });
        await flush();

        assert.equal(count(PREVIEW_A), 1);
        assert.equal(count(METADATA_A), 1);
        release(PREVIEW_A);
        release(METADATA_A);
        await flush();
        assert.deepEqual(second.panels.preview.data.value, { url: PREVIEW_A });
        second.unmount();
    });
});

test("deletion and a 404 still clear the dataset's cached data, quality audit included", async () => {
    await withServer(async ({ release }) => {
        const quality = getDatasetQuality("a");
        const metadata = getDatasetMetadata("a");
        release(QUALITY_A, 200, { status: "valid" });
        release(METADATA_A);
        await Promise.all([quality, metadata]);

        evictDatasetCache("a"); // deleteDataset()'s default eviction
        assert.equal(getCachedResponse(QUALITY_A), undefined);
        assert.equal(getCachedResponse(METADATA_A), undefined);

        const again = getDatasetQuality("a");
        release(QUALITY_A, 200, { status: "valid" });
        await again;
        assert.notEqual(getCachedResponse(QUALITY_A), undefined);

        const preview = getDatasetPreview("a");
        release(PREVIEW_A, 404, { detail: "Dataset not found." });
        await assert.rejects(preview);
        assert.equal(getCachedResponse(QUALITY_A), undefined);
    });
});

// =========================================================
// THE COMPONENTS ARE WIRED AS SIMULATED ABOVE
// =========================================================

test("no component requests /profile in a normal workflow", () => {
    for (const file of [
        ["components", "workspace", "ContextBar.vue"],
        ["components", "DataPreview.vue"],
        ["components", "DatasetMetadata.vue"],
        ["components", "AnalyticsBuilder.vue"],
        ["components", "DataQuality.vue"],
        ["components", "Dashboard.vue"],
    ]) {
        assert.doesNotMatch(read(...file), /getDatasetProfile|datasetUrls\.profile/, file.join("/"));
    }
    // DatasetOverview still calls it, but is not mounted anywhere.
    for (const file of ["Dashboard.vue", "AnalyticsBuilder.vue", "DataPreview.vue"]) {
        assert.doesNotMatch(read("components", file), /<DatasetOverview|DatasetOverview\.vue"/, file);
    }
});

test("Data and Schema panels load on activation (not on mount) and Dashboard passes their tab state", () => {
    const preview = read("components", "DataPreview.vue");
    const schema = read("components", "DatasetMetadata.vue");
    const dashboard = read("components", "Dashboard.vue");

    for (const source of [preview, schema]) {
        assert.doesNotMatch(source, /onMounted/);
        assert.match(source, /useDatasetResource\(\{\s*datasetId: \(\) => props\.datasetId,\s*active: \(\) => props\.active,/);
    }
    assert.match(dashboard, /<DataPreview[^>]*:active="workspaceTab === 'data'"/s);
    assert.match(dashboard, /<DatasetMetadata[^>]*:active="workspaceTab === 'schema'"/s);
    // Column details come from /metadata only.
    assert.doesNotMatch(preview, /profile:/);
    assert.match(preview, /metadata\.value\?\.row_count/);
});

test("AnalyticsBuilder: metadata only from the Suggest questions button - not mount, focus or submit", () => {
    const source = read("components", "AnalyticsBuilder.vue");

    assert.doesNotMatch(source, /onMounted/);
    assert.doesNotMatch(source, /@focus/); // neither composer loads metadata on focus
    assert.doesNotMatch(source, /getDatasetMetadata/); // only through useSuggestionMetadata
    assert.match(source, /useSuggestionMetadata\(/);
    assert.equal(source.match(/requestSuggestions/g)?.length, 2); // destructured + the button
    assert.match(source, /v-if="showSuggestButton"[^>]*@click="requestSuggestions"/s);

    const analyzeBody = source.slice(source.indexOf("async function analyze()"), source.indexOf("async function analyze()") + 4000);
    assert.doesNotMatch(analyzeBody, /metadata/i);

    // The submit buttons never depend on metadata state.
    for (const match of source.matchAll(/:disabled="([^"]*)"/g)) {
        assert.doesNotMatch(match[1], /metadata/i);
    }
});
