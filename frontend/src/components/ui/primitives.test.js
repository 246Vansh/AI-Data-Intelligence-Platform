// Run with: node --test src/components/ui/primitives.test.js
// Server-renders the Reka-based primitives through Vite's SSR loader
// (no DOM library needed). Interaction behaviour - focus trapping,
// arrow-key navigation, Esc - is Reka's own tested contract; these
// tests pin down OUR wiring: ARIA attributes, always-mounted tab panels,
// dialog naming, close controls and token styling.
import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";

const UI_DIR = dirname(fileURLToPath(import.meta.url));

let server;
const C = {};
const warnings = [];

// Reka portals (open dialogs, toasts) only render once mounted in a
// browser. For SSR, this in-memory, test-only transform adds Reka's own
// `force-mount` to those portals, so OUR real templates render; the
// component files on disk are not changed.
const forceMountPortals = {
    name: "test-force-mount-portals",
    enforce: "pre",
    transform(code, id) {
        if (/ui[\\/](Dialog|Toaster)\.vue$/.test(id)) {
            return code
                .replace(/<DialogPortal>/g, "<DialogPortal force-mount>")
                .replace(/<ToastRoot /g, "<ToastRoot force-mount ");
        }
    },
};

before(async () => {
    server = await createServer({
        configFile: false,
        root: join(UI_DIR, "..", "..", ".."),
        logLevel: "silent",
        plugins: [forceMountPortals, vue()],
        server: { middlewareMode: true, hmr: false },
        appType: "custom",
    });
    for (const name of ["Tabs", "TabPanel", "Dialog", "Menu", "Tooltip", "SegmentedControl", "ResizeHandle", "Toaster"]) {
        C[name] = (await server.ssrLoadModule(`/src/components/ui/${name}.vue`)).default;
    }
    // Native import: the same (externalized) reka-ui instance the .vue
    // files use, so SplitterGroup's context reaches the handle.
    C.reka = await import("reka-ui");
    C.toast = await server.ssrLoadModule("/src/services/toast.js");
});

after(async () => {
    await server?.close();
});

async function render(vnodeFactory) {
    const app = createSSRApp({ render: vnodeFactory });
    app.config.warnHandler = (message) => warnings.push(message);
    const ctx = {};
    const html = (await renderToString(app, ctx)).replace(/<!--[^>]*-->/g, "");
    const teleported = Object.values(ctx.teleports || {}).join("").replace(/<!--[^>]*-->/g, "");
    return { html, teleported };
}

const takeWarnings = () => warnings.splice(0, warnings.length);

// =========================================================
// TABS
// =========================================================

const ITEMS = [
    { value: "analyze", label: "Analyze", icon: "sparkle" },
    { value: "schema", label: "Schema", icon: "columns" },
];

test("Tabs: accessible tablist with the active tab selected", async () => {
    const { html } = await render(() =>
        h(C.Tabs, { modelValue: "analyze", items: ITEMS, label: "Workspace" }),
    );

    assert.match(html, /role="tablist"[^>]*aria-label="Workspace"|aria-label="Workspace"[^>]*role="tablist"/);
    assert.equal((html.match(/role="tab"/g) || []).length, 2);
    assert.match(html, /aria-selected="true"[^>]*>[\s\S]*?Analyze/);
    assert.match(html, /aria-selected="false"[^>]*>[\s\S]*?Schema/);
    assert.deepEqual(takeWarnings(), []);
});

test("Tabs: inactive panels stay MOUNTED (hidden), so their state survives", async () => {
    const { html } = await render(() =>
        h(C.Tabs, { modelValue: "analyze", items: ITEMS, label: "Workspace" }, {
            default: () => [
                h(C.TabPanel, { value: "analyze" }, { default: () => h("p", "ANALYSIS RESULT") }),
                h(C.TabPanel, { value: "schema" }, { default: () => h("p", "SCHEMA CONTENT") }),
            ],
        }),
    );

    assert.match(html, /ANALYSIS RESULT/);
    assert.match(html, /SCHEMA CONTENT/, "inactive panel was unmounted");
    assert.match(html, /role="tabpanel"[^>]*data-state="inactive"[^>]*>|data-state="inactive"[^>]*role="tabpanel"/);
    assert.match(html, /data-\[state=inactive\]:hidden/);
});

test("Tabs: #end slot renders toolbar actions", async () => {
    const { html } = await render(() =>
        h(C.Tabs, { modelValue: "analyze", items: ITEMS, label: "Workspace" }, { end: () => h("button", "Refresh") }),
    );
    assert.match(html, /<button>Refresh<\/button>/);
});

// =========================================================
// DIALOG / SHEET
// =========================================================

test("Dialog: closed renders nothing", async () => {
    const { html, teleported } = await render(() => h(C.Dialog, { open: false, title: "Upload dataset" }));
    assert.doesNotMatch(html + teleported, /role="dialog"/);
});

test("Dialog: open renders a named, described modal with a labelled close button", async () => {
    const { teleported } = await render(() =>
        h(C.Dialog, { open: true, title: "Upload dataset", description: "CSV files only." },
            { default: () => h("p", "BODY"), footer: () => h("button", "Upload") }),
    );

    assert.match(teleported, /role="dialog"/);
    const labelledBy = teleported.match(/aria-labelledby="([^"]+)"/)?.[1];
    assert.ok(labelledBy, "dialog has no aria-labelledby");
    assert.match(teleported, new RegExp(`id="${labelledBy}"[^>]*>\\s*Upload dataset`));
    assert.match(teleported, /aria-describedby="[^"]+"/);
    assert.match(teleported, /CSV files only\./);
    assert.match(teleported, /aria-label="Close"/);
    assert.match(teleported, />BODY</);
    assert.match(teleported, /<footer[\s\S]*>Upload<\/button>/);
    assert.match(teleported, /animate-dialog-in/);
});

test("Dialog: sides map to sheets", async () => {
    for (const [side, cls] of [["right", "animate-sheet-in-right"], ["left", "animate-sheet-in-left"], ["bottom", "animate-sheet-in-bottom"]]) {
        const { teleported } = await render(() => h(C.Dialog, { open: true, title: "Sheet", side }));
        assert.match(teleported, new RegExp(cls), side);
    }
    const { teleported } = await render(() => h(C.Dialog, { open: true, title: "Sheet", side: "bottom" }));
    assert.match(teleported, /rounded-t-panel/);
});

test("Dialog: hideTitle keeps the accessible name but hides it visually", async () => {
    const { teleported } = await render(() => h(C.Dialog, { open: true, title: "Datasets", hideTitle: true }));
    assert.match(teleported, /<header[^>]*sr-only/);
    assert.match(teleported, /Datasets/);
});

// =========================================================
// MENU / TOOLTIP
// =========================================================

test("Menu: trigger is the slotted element with menu semantics (closed)", async () => {
    const { html, teleported } = await render(() =>
        h(C.Menu, { items: [{ key: "refresh", label: "Refresh", icon: "refresh" }] }, {
            trigger: () => h("button", { "aria-label": "Dataset actions" }, "⋯"),
        }),
    );
    assert.match(html, /<button[^>]*aria-haspopup="menu"/);
    assert.match(html, /aria-label="Dataset actions"/);
    assert.match(html, /aria-expanded="false"/);
    assert.doesNotMatch(teleported, /role="menu"/);
});

test("Tooltip: renders only its trigger until hovered/focused", async () => {
    const { html, teleported } = await render(() =>
        h(C.Tooltip, { content: "sales_2024_final_v2.csv" }, { default: () => h("button", "sales_2024…") }),
    );
    assert.match(html, /<button[^>]*>sales_2024…<\/button>/);
    assert.doesNotMatch(html + teleported, /sales_2024_final_v2\.csv/);
});

// =========================================================
// SEGMENTED CONTROL / RESIZE HANDLE
// =========================================================

test("SegmentedControl: labelled group, one option on", async () => {
    const { html } = await render(() =>
        h(C.SegmentedControl, {
            modelValue: "chart",
            label: "Result view",
            items: [{ value: "chart", label: "Chart", icon: "bar-chart" }, { value: "table", label: "Table", icon: "table" }],
        }),
    );
    assert.match(html, /aria-label="Result view"/);
    assert.match(html, /data-state="on"[^>]*>[\s\S]*?Chart/);
    assert.match(html, /data-state="off"[^>]*>[\s\S]*?Table/);
    assert.match(html, /aria-pressed="true"|aria-checked="true"/);
});

test("ResizeHandle: a labelled window-splitter separator between panels", async () => {
    const { SplitterGroup, SplitterPanel } = C.reka;
    const { html } = await render(() =>
        h(SplitterGroup, { direction: "horizontal" }, {
            default: () => [
                h(SplitterPanel, { defaultSize: 70 }, { default: () => "MAIN" }),
                h(C.ResizeHandle, { label: "Resize findings inspector" }),
                h(SplitterPanel, { defaultSize: 30 }, { default: () => "RAIL" }),
            ],
        }),
    );
    assert.match(html, /role="separator"/);
    assert.match(html, /aria-label="Resize findings inspector"/);
    assert.match(html, /MAIN[\s\S]*RAIL/);
});

// =========================================================
// TOASTS
// =========================================================

test("toast queue: add, cap at 3, dismiss, clear", () => {
    const { toast, dismissToast, clearToasts, toasts } = C.toast;
    clearToasts();

    assert.equal(toast({ title: "" }), null);
    const first = toast({ title: "One" });
    toast({ title: "Two" });
    toast({ title: "Three" });
    toast({ title: "Four", tone: "success" });

    assert.deepEqual(toasts.items.map((t) => t.title), ["Two", "Three", "Four"]);
    assert.equal(toasts.items.find((t) => t.id === first), undefined);

    dismissToast(toasts.items[0].id);
    assert.deepEqual(toasts.items.map((t) => t.title), ["Three", "Four"]);

    clearToasts();
    assert.equal(toasts.items.length, 0);
});

// Individual toasts teleport into the viewport element, which exists only
// once mounted in a browser - so SSR can verify the live region and
// viewport wiring, and the queue logic is covered above. Rendering of an
// actual toast is part of the browser verification checklist.
test("Toaster: notifications live region + viewport are wired", async () => {
    C.toast.clearToasts();
    C.toast.toast({ title: "sales.csv uploaded" });

    const { html } = await render(() => h(C.Toaster));

    assert.match(html, /role="region"[^>]*aria-label="Notifications \(F8\)"/);
    assert.match(html, /<ol[^>]*class="fixed bottom-4 right-4/);
    assert.deepEqual(takeWarnings(), []);
    C.toast.clearToasts();
});
