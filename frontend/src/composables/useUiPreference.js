import { useStorage } from "@vueuse/core";

// =========================================================
// UI PREFERENCES (the ONLY browser-storage access in the app)
// =========================================================
//
// Remembers small interface choices per browser - e.g. whether the
// dataset library is docked open. Nothing else may use browser storage:
// session tokens are HttpOnly cookies managed by the backend, and
// credentials, dataset contents and analysis results are never persisted
// in the browser (enforced by a source scan in services/auth.test.js,
// which allows browser storage in this file only).
//
// Guard rails, so this cannot become a general-purpose store:
// - keys are namespaced "ui.<name>" (lowercase, dots/dashes only);
// - only booleans and finite numbers are accepted as values.

const KEY_PATTERN = /^[a-z][a-z0-9.-]*$/;

export function uiPreferenceKey(name) {
    if (typeof name !== "string" || !KEY_PATTERN.test(name)) {
        throw new Error(`Invalid UI preference name: ${name}`);
    }
    return `ui.${name}`;
}

// Storage adapter for Reka SplitterGroup's `storage` prop (remembered
// pane widths). Without it, Reka would write to localStorage itself,
// outside this module. Only layouts made purely of numbers (sizes) are
// stored, under "ui.splitter.<id>"; anything else is ignored.
//
// Consequence, deliberate (Phase 3 browser validation): layouts with a
// px-sized panel - the library and the inspectors - carry a
// `sizeUnits: { n: "px" }` marker and are therefore NOT stored. Reka
// saves those panels as a percentage of the group width, so a restored
// "px" panel comes back at a different width whenever the window (or a
// transient layout during load) differs - letting them through shrank
// the library to its 200px minimum. Those panels open at their designed
// widths instead.
function isNumbersOnly(value) {
    if (typeof value === "number") {
        return Number.isFinite(value);
    }
    if (Array.isArray(value)) {
        return value.every(isNumbersOnly);
    }
    if (value && typeof value === "object") {
        return Object.values(value).every(isNumbersOnly);
    }
    return false;
}

function browserStorage() {
    try {
        return typeof window === "undefined" ? null : window.localStorage;
    } catch {
        return null; // storage blocked (privacy mode, policies)
    }
}

export const splitterStorage = {
    getItem(name) {
        try {
            return browserStorage()?.getItem(`ui.splitter.${name}`) ?? null;
        } catch {
            return null;
        }
    },
    setItem(name, value) {
        try {
            if (isNumbersOnly(JSON.parse(value))) {
                browserStorage()?.setItem(`ui.splitter.${name}`, value);
            }
        } catch {
            // Not JSON / storage unavailable: just don't remember it.
        }
    },
};

export function useUiPreference(name, defaultValue) {
    const isBoolean = typeof defaultValue === "boolean";
    const isNumber = typeof defaultValue === "number" && Number.isFinite(defaultValue);

    if (!isBoolean && !isNumber) {
        throw new Error("UI preferences may only hold booleans or finite numbers.");
    }

    // browserStorage() returns null when storage is blocked (privacy
    // mode, sandboxed frames, policies) - reading window.localStorage
    // then throws. useStorage without a storage keeps the preference in
    // memory for the session instead of breaking the panel that asked.
    return useStorage(uiPreferenceKey(name), defaultValue, browserStorage() ?? undefined, {
        // A malformed stored value falls back to the default rather than
        // leaking into the UI.
        serializer: {
            read: (raw) => {
                if (isBoolean) {
                    return raw === "true" ? true : raw === "false" ? false : defaultValue;
                }
                const number = Number(raw);
                return Number.isFinite(number) ? number : defaultValue;
            },
            write: (value) => String(isBoolean ? Boolean(value) : Number(value)),
        },
    });
}
