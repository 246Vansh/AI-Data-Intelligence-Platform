// Run with: node --test src/composables/useWorkspaceTab.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { effectScope } from "vue";

import { LEGACY_ANCHORS, WORKSPACE_TABS, resolveHash, useWorkspaceTab } from "./useWorkspaceTab.js";

// Minimal browser-like window: a history stack whose Back/Forward
// restore the hash and fire popstate, like a real browser.
function fakeWindow(initialHash = "") {
    const listeners = { popstate: new Set(), hashchange: new Set() };
    const entries = [initialHash];
    let index = 0;
    const calls = { push: 0, replace: 0 };

    const win = {
        location: { pathname: "/", search: "", hash: initialHash },
        history: {
            state: null,
            pushState(_state, _title, url) {
                calls.push += 1;
                entries.splice(index + 1);
                entries.push(url.slice(url.indexOf("#")));
                index = entries.length - 1;
                win.location.hash = entries[index];
            },
            replaceState(_state, _title, url) {
                calls.replace += 1;
                entries[index] = url.slice(url.indexOf("#"));
                win.location.hash = entries[index];
            },
        },
        addEventListener: (type, fn) => listeners[type].add(fn),
        removeEventListener: (type, fn) => listeners[type].delete(fn),
        back() {
            index = Math.max(0, index - 1);
            win.location.hash = entries[index];
            listeners.popstate.forEach((fn) => fn());
        },
        forward() {
            index = Math.min(entries.length - 1, index + 1);
            win.location.hash = entries[index];
            listeners.popstate.forEach((fn) => fn());
        },
        typeHash(hash) {
            win.location.hash = hash;
            listeners.hashchange.forEach((fn) => fn());
        },
    };
    return { win, entries, calls, listeners };
}

function mount(win, options = {}) {
    const scope = effectScope();
    const api = scope.run(() => useWorkspaceTab({ win, ...options }));
    return { ...api, stop: () => scope.stop() };
}

test("tabs and legacy anchors resolve to the right tab", () => {
    assert.deepEqual(WORKSPACE_TABS, ["analyze", "data", "schema", "quality"]);
    assert.equal(resolveHash("#schema").tab, "schema");
    assert.equal(resolveHash("").tab, "analyze");
    assert.equal(resolveHash("#nonsense").tab, "analyze");
    assert.equal(resolveHash("#nonsense").rewrite, true);
    assert.equal(resolveHash("").rewrite, false);

    const expected = {
        "ask-data": "analyze", insights: "analyze", upload: "analyze",
        overview: "data", "data-preview": "data", "dataset-schema": "schema", quality: "quality",
    };
    for (const [anchor, tab] of Object.entries(expected)) {
        assert.equal(resolveHash(`#${anchor}`).tab, tab, anchor);
    }
    assert.equal(resolveHash("#upload").upload, true);
    assert.equal(Object.keys(LEGACY_ANCHORS).length, 6);
});

test("initial hash selects the tab; a legacy anchor is rewritten in place", () => {
    const direct = fakeWindow("#quality");
    assert.equal(mount(direct.win).tab.value, "quality");
    assert.equal(direct.calls.replace, 0);

    const legacy = fakeWindow("#dataset-schema");
    const api = mount(legacy.win);
    assert.equal(api.tab.value, "schema");
    assert.equal(legacy.win.location.hash, "#schema");
    assert.equal(legacy.calls.push, 0, "rewriting must not add a history entry");
});

test("#upload opens on Analyze and requests the upload dialog", () => {
    const { win } = fakeWindow("#upload");
    const api = mount(win);
    assert.equal(api.tab.value, "analyze");
    assert.equal(api.initialUploadRequested, true);
    assert.equal(win.location.hash, "#analyze");
});

test("choosing tabs pushes history; Back and Forward restore them", () => {
    const { win } = fakeWindow("");
    const api = mount(win);

    api.setTab("data");
    api.setTab("schema");
    assert.equal(win.location.hash, "#schema");

    win.back();
    assert.equal(api.tab.value, "data");
    win.back();
    assert.equal(api.tab.value, "analyze");
    win.forward();
    assert.equal(api.tab.value, "data");
    win.forward();
    assert.equal(api.tab.value, "schema");
});

test("re-selecting the current tab or an invalid tab adds no history", () => {
    const { win, calls } = fakeWindow("#data");
    const api = mount(win);

    api.setTab("data");
    api.setTab("not-a-tab");
    assert.equal(calls.push, 0);
    assert.equal(api.tab.value, "data");
});

test("editing the hash / following an old anchor link switches tab", () => {
    let uploads = 0;
    const { win } = fakeWindow("#analyze");
    const api = mount(win, { onUploadRequested: () => { uploads += 1; } });

    win.typeHash("#overview");
    assert.equal(api.tab.value, "data");
    assert.equal(win.location.hash, "#data");

    win.typeHash("#upload");
    assert.equal(api.tab.value, "analyze");
    assert.equal(uploads, 1);
});

test("listeners are removed when the owning scope stops", () => {
    const { win, listeners } = fakeWindow("");
    const api = mount(win);
    assert.equal(listeners.popstate.size, 1);
    api.stop();
    assert.equal(listeners.popstate.size, 0);
    assert.equal(listeners.hashchange.size, 0);
});

test("works without a window (SSR): default tab, no errors", () => {
    const scope = effectScope();
    const api = scope.run(() => useWorkspaceTab({ win: null }));
    assert.equal(api.tab.value, "analyze");
    api.setTab("schema");
    assert.equal(api.tab.value, "schema");
    scope.stop();
});
