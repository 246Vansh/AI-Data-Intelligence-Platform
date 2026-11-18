import { getCurrentScope, onScopeDispose, ref } from "vue";

// =========================================================
// WORKSPACE TAB <-> URL HASH
// =========================================================
//
// The selected workspace tab lives in the URL hash (#analyze, #data,
// #schema, #quality), so a tab can be linked to and the browser's Back /
// Forward buttons move between tabs.
//
// - Choosing a tab PUSHES a history entry (Back returns to the previous
//   tab). popstate / hashchange bring the UI back in sync.
// - The page's old section anchors (#ask-data, #overview, ...) still
//   work: they are mapped to the tab that now holds that content and the
//   URL is rewritten in place (replaceState - no extra history entry).
//   #upload maps to Analyze and also asks the shell to open the upload
//   dialog.
// - No router dependency: this is the only navigation state the app has.

export const WORKSPACE_TABS = Object.freeze(["analyze", "data", "schema", "quality"]);

export const DEFAULT_TAB = "analyze";

export const LEGACY_ANCHORS = Object.freeze({
    "ask-data": "analyze",
    insights: "analyze",
    upload: "analyze",
    overview: "data",
    "data-preview": "data",
    "dataset-schema": "schema",
});

// "#data" -> { tab: "data", rewrite: false, upload: false }
export function resolveHash(hash) {
    const key = String(hash || "").replace(/^#/, "").trim();

    if (WORKSPACE_TABS.includes(key)) {
        return { tab: key, rewrite: false, upload: false };
    }

    if (Object.hasOwn(LEGACY_ANCHORS, key)) {
        return { tab: LEGACY_ANCHORS[key], rewrite: true, upload: key === "upload" };
    }

    // Empty or unknown hash: default tab; rewrite only an unknown one.
    return { tab: DEFAULT_TAB, rewrite: key !== "", upload: false };
}

export function useWorkspaceTab({ win = typeof window === "undefined" ? null : window, onUploadRequested } = {}) {
    const initial = resolveHash(win?.location?.hash);
    const tab = ref(initial.tab);

    function urlFor(name) {
        const { pathname = "", search = "" } = win?.location || {};
        return `${pathname}${search}#${name}`;
    }

    function syncFromLocation() {
        const resolved = resolveHash(win?.location?.hash);
        tab.value = resolved.tab;

        if (resolved.rewrite) {
            win?.history?.replaceState(win.history.state, "", urlFor(resolved.tab));
        }
        if (resolved.upload) {
            onUploadRequested?.();
        }
    }

    function setTab(next) {
        if (!WORKSPACE_TABS.includes(next) || next === tab.value) {
            return;
        }

        tab.value = next;
        win?.history?.pushState(win.history.state, "", urlFor(next));
    }

    if (initial.rewrite) {
        win?.history?.replaceState(win.history?.state ?? null, "", urlFor(initial.tab));
    }

    if (win) {
        win.addEventListener("popstate", syncFromLocation);
        win.addEventListener("hashchange", syncFromLocation);

        if (getCurrentScope()) {
            onScopeDispose(() => {
                win.removeEventListener("popstate", syncFromLocation);
                win.removeEventListener("hashchange", syncFromLocation);
            });
        }
    }

    return {
        tab,
        setTab,
        // True when the page was opened at the legacy #upload anchor.
        initialUploadRequested: initial.upload,
    };
}
