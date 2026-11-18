// Run with: node --test src/components/ui/ui.test.js
// Built-in node:test - no test framework dependency. The .vue files are
// compiled by Vite's own SSR module loader and rendered with Vue's
// server renderer (both already part of the project), because none of
// these components is imported by the app yet - so `vite build` alone
// would never compile them.
import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";

const UI_DIR = dirname(fileURLToPath(import.meta.url));
const STYLE_CSS = readFileSync(join(UI_DIR, "..", "..", "style.css"), "utf8");

let server;
let Icon, ICONS, Panel, Button, StatusChip, EmptyState;
const warnings = [];
const originalWarn = console.warn;

before(async () => {
    server = await createServer({
        configFile: false,
        root: join(UI_DIR, "..", "..", ".."),
        logLevel: "silent",
        plugins: [vue()],
        server: { middlewareMode: true, hmr: false },
        appType: "custom",
    });

    const load = (name) => server.ssrLoadModule(`/src/components/ui/${name}.vue`);
    const iconModule = await load("Icon");
    Icon = iconModule.default;
    ICONS = iconModule.ICONS;
    Panel = (await load("Panel")).default;
    Button = (await load("Button")).default;
    StatusChip = (await load("StatusChip")).default;
    EmptyState = (await load("EmptyState")).default;

    console.warn = (...args) => warnings.push(args.join(" "));
});

after(async () => {
    console.warn = originalWarn;
    await server?.close();
});

async function render(component, props = {}, slots = {}) {
    const app = createSSRApp({ render: () => h(component, props, slots) });
    app.config.warnHandler = (message) => warnings.push(message);
    // Drop SSR hydration markers (<!--[-->, <!--v-if-->) so assertions
    // read like the rendered DOM.
    return (await renderToString(app)).replace(/<!--[^>]*-->/g, "");
}

function takeWarnings() {
    return warnings.splice(0, warnings.length);
}

// =========================================================
// ICON
// =========================================================

test("Icon: every icon renders its paths with a non-scaling 1.5 stroke", async () => {
    const names = Object.keys(ICONS);
    assert.ok(names.length >= 30, `expected a full set, got ${names.length}`);

    for (const name of names) {
        const html = await render(Icon, { name });
        // Lucide draws with path/circle/rect/line/...; every shape must
        // keep a constant 1.5px rendered stroke.
        const shapeCount = (html.match(/<(path|circle|rect|line|polyline|polygon|ellipse) /g) || []).length;

        assert.ok(shapeCount > 0, `${name} renders no shapes`);
        assert.equal((html.match(/vector-effect="non-scaling-stroke"/g) || []).length, shapeCount, name);
        assert.match(html, /stroke-width="1\.5"/);
        assert.match(html, /viewbox="0 0 24 24"/i); // SSR lowercases the attribute name
        assert.match(html, /class="lucide /, `${name} is not a Lucide icon`);
    }
    assert.deepEqual(takeWarnings(), []);
});

test("Icon: decorative by default, labelled when given a label", async () => {
    const decorative = await render(Icon, { name: "search" });
    assert.match(decorative, /aria-hidden="true"/);
    assert.doesNotMatch(decorative, /role="img"/);
    assert.doesNotMatch(decorative, /<title>/);

    const labelled = await render(Icon, { name: "refresh", label: "Refresh data" });
    assert.match(labelled, /role="img"/);
    assert.match(labelled, /aria-label="Refresh data"/);
    assert.match(labelled, /<title>Refresh data<\/title>/);
    assert.doesNotMatch(labelled, /aria-hidden/);
});

test("Icon: only the defined sizes are allowed", async () => {
    for (const size of [14, 16, 20]) {
        const html = await render(Icon, { name: "check", size });
        assert.match(html, new RegExp(`width="${size}" height="${size}"`));
    }
    assert.deepEqual(takeWarnings(), []);

    await render(Icon, { name: "check", size: 18 });
    assert.ok(takeWarnings().some((w) => /size/.test(w)));
});

test("Icon: an unknown name warns and renders no paths", async () => {
    const html = await render(Icon, { name: "not-an-icon" });

    assert.doesNotMatch(html, /<path /);
    assert.ok(takeWarnings().some((w) => /name/.test(w)));
});

test("Icon: covers every meaning the current app expresses with glyphs/SVGs", () => {
    const required = [
        "check", "x", "plus", "upload", "refresh", "search", "trash", "log-out",
        "arrow-right", "arrow-up", "arrow-down", "trend-up", "compare", "chevron-down",
        "overview", "table", "columns", "rows", "menu", "database", "file", "file-text",
        "copy", "cpu", "bar-chart", "code", "sparkle", "lightbulb", "message", "target",
        "shield-check", "info", "error", "warning", "user",
    ];
    for (const name of required) {
        assert.ok(Object.hasOwn(ICONS, name), `missing icon: ${name}`);
    }
});

// =========================================================
// BUTTON
// =========================================================

// The native attribute, not the `disabled:` Tailwind variant in class.
const DISABLED_ATTR = /<button[^>]*\sdisabled(?=[\s>])/;

test("Button: native <button>, type defaults to button (never submits by accident)", async () => {
    const html = await render(Button, {}, { default: () => "Cancel" });

    assert.match(html, /^<button[^>]*\btype="button"/);
    assert.match(html, />Cancel<\/button>$/);
    assert.doesNotMatch(html, DISABLED_ATTR);
});

test("Button: type, attributes and aria pass through to the native element", async () => {
    const html = await render(
        Button,
        { type: "submit", "aria-label": "Run analysis", title: "Run", form: "f1", "data-test": "go" },
        { default: () => "Run" },
    );

    assert.match(html, /type="submit"/);
    assert.match(html, /aria-label="Run analysis"/);
    assert.match(html, /title="Run"/);
    assert.match(html, /form="f1"/);
    assert.match(html, /data-test="go"/);
});

test("Button: variants and sizes use design tokens", async () => {
    const primary = await render(Button, { variant: "primary" }, { default: () => "Save" });
    const secondary = await render(Button, { variant: "secondary", size: "sm" }, { default: () => "Edit" });
    const danger = await render(Button, { variant: "danger" }, { default: () => "Delete" });

    assert.match(primary, /bg-forest/);
    assert.match(primary, /text-canvas/);
    assert.match(secondary, /bg-surface/);
    assert.match(secondary, /h-8/);
    assert.match(danger, /bg-danger/);
    assert.match(danger, /text-surface/);
    assert.match(primary, /rounded-control/);
    assert.deepEqual(takeWarnings(), []);

    await render(Button, { variant: "fancy" }, { default: () => "x" });
    assert.ok(takeWarnings().some((w) => /variant/.test(w)));
});

test("Button: disabled state is the native disabled attribute", async () => {
    const html = await render(Button, { disabled: true }, { default: () => "Save" });

    assert.match(html, DISABLED_ATTR);
    assert.doesNotMatch(html, /aria-busy/);
});

test("Button: loading disables, sets aria-busy, shows a spinner and keeps the label", async () => {
    const html = await render(
        Button,
        { loading: true, icon: "upload" },
        { default: () => "Upload" },
    );

    assert.match(html, DISABLED_ATTR);
    assert.match(html, /aria-busy="true"/);
    assert.match(html, /animate-spin/);
    assert.doesNotMatch(html, /<svg/); // spinner replaces the icon
    assert.match(html, /Upload<\/button>$/);
});

test("Button: leading icon is decorative and sized to the button", async () => {
    const md = await render(Button, { icon: "upload" }, { default: () => "Upload" });
    const sm = await render(Button, { icon: "upload", size: "sm" }, { default: () => "Upload" });

    assert.match(md, /<svg[^>]*width="16" height="16"[^>]*aria-hidden="true"/);
    assert.match(sm, /<svg[^>]*width="14" height="14"/);
});

// =========================================================
// STATUS CHIP
// =========================================================

test("StatusChip: each tone has its own fill, icon shape and a visible label", async () => {
    const expectations = {
        success: { fill: "bg-forest-soft", path: "lucide-check" },
        warning: { fill: "bg-warn-soft", path: "lucide-triangle-alert" },
        error: { fill: "bg-danger-soft", path: "lucide-circle-alert" },
    };

    for (const [tone, { fill, path }] of Object.entries(expectations)) {
        const html = await render(StatusChip, { tone, label: `${tone} label` });
        assert.match(html, new RegExp(fill), tone);
        assert.ok(html.includes(`${path} `) || html.includes(`${path}"`), `${tone} icon`);
        assert.match(html, new RegExp(`>${tone} label<`), tone);
        assert.match(html, /aria-hidden="true"/);
    }

    const neutral = await render(StatusChip, { label: "Idle" });
    assert.match(neutral, /bg-sunken/);
    assert.doesNotMatch(neutral, /<svg/);
    assert.match(neutral, />Idle</);
    assert.deepEqual(takeWarnings(), []);
});

test("StatusChip: label is required and an unknown tone warns", async () => {
    await render(StatusChip, { tone: "purple", label: "x" });
    assert.ok(takeWarnings().some((w) => /tone/.test(w)));

    await render(StatusChip, {});
    assert.ok(takeWarnings().some((w) => /label/.test(w)));
});

// =========================================================
// PANEL
// =========================================================

test("Panel: a bare panel is just the surface - no header, padded body", async () => {
    const html = await render(Panel, {}, { default: () => "Body" });

    assert.match(html, /^<section/);
    assert.match(html, /rounded-panel/);
    assert.match(html, /bg-surface/);
    assert.match(html, /shadow-panel/);
    assert.match(html, /overflow-clip/);
    assert.doesNotMatch(html, /<header/);
    assert.doesNotMatch(html, /aria-labelledby/);
    assert.match(html, /px-5 pb-5 pt-4[^>]*>Body/);
});

test("Panel: title becomes the heading that labels the section", async () => {
    const html = await render(Panel, { title: "Schema", description: "12 columns" }, { default: () => "x" });

    const id = html.match(/<h2 id="([^"]+)"/)?.[1];
    assert.ok(id);
    assert.match(html, new RegExp(`aria-labelledby="${id}"`));
    assert.match(html, />Schema<\/h2>/);
    assert.match(html, />12 columns</);
});

test("Panel: headingLevel, element choice, actions, footer and flush", async () => {
    const html = await render(
        Panel,
        { title: "Preview", headingLevel: 3, as: "div", flush: true },
        {
            default: () => "TABLE",
            actions: () => h("button", "Refresh"),
            footer: () => "Showing 100 rows",
        },
    );

    assert.match(html, /^<div/);
    assert.match(html, /<h3 /);
    assert.doesNotMatch(html, /aria-labelledby/); // only sections are labelled landmarks
    assert.match(html, /<button>Refresh<\/button>/);
    assert.match(html, /<footer[^>]*>Showing 100 rows<\/footer>/);
    assert.match(html, /border-b border-line pb-3\.5/); // flush header is ruled off
    assert.match(html, /<div class="">TABLE<\/div>/); // flush body has no padding
});

test("Panel: actions alone still render a header", async () => {
    const html = await render(Panel, {}, { default: () => "x", actions: () => "A" });

    assert.match(html, /<header/);
    assert.doesNotMatch(html, /<h2/);
});

// =========================================================
// EMPTY STATE
// =========================================================

test("EmptyState: title only", async () => {
    const html = await render(EmptyState, { title: "No datasets yet" });

    assert.match(html, />No datasets yet</);
    assert.doesNotMatch(html, /<svg/);
});

test("EmptyState: icon, description and action slot", async () => {
    const html = await render(
        EmptyState,
        { title: "No datasets yet", description: "Upload a CSV to start.", icon: "upload" },
        { action: () => h("button", "Upload CSV") },
    );

    assert.match(html, /<svg[^>]*width="20" height="20"[^>]*aria-hidden="true"/);
    assert.match(html, />Upload a CSV to start\.</);
    assert.match(html, /<button>Upload CSV<\/button>/);
});

// =========================================================
// DESIGN TOKENS ONLY
// =========================================================

test("ui components use Phase 1 tokens exclusively", () => {
    const sources = readdirSync(UI_DIR)
        .filter((name) => name.endsWith(".vue"))
        .map((name) => [
            name,
            // Scan code, not prose: drop // line comments and <!-- --> blocks.
            readFileSync(join(UI_DIR, name), "utf8")
                .replace(/<!--[\s\S]*?-->/g, "")
                .replace(/^\s*\/\/.*$/gm, ""),
        ]);

    const colorUtil =
        /\b(?:bg|text|border|ring|outline|from|via|to|fill|stroke|divide)-([a-z]+(?:-[a-z]+)*?)(?:\/\d+)?(?=["'\s:])/g;
    const NON_COLOR = new Set([
        "current", "transparent", "center", "left", "right", "caption", "data", "body", "lead",
        "title", "display", "t", "b", "l", "r", "x", "y", "solid", "none", "offset",
    ]);

    for (const [name, source] of sources) {
        assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b/, `${name}: raw hex color`);
        assert.doesNotMatch(source, /-\[#/, `${name}: arbitrary color`);
        assert.doesNotMatch(
            source,
            /\b(?:slate|gray|zinc|violet|indigo|blue|emerald|green|amber|red|rose|fuchsia|white|black)-?\d*\b(?=["'\s])/,
            `${name}: Tailwind default palette color`,
        );
        assert.doesNotMatch(source, /bg-gradient|shadow-(?:sm|md|lg|xl|2xl)\b|rounded-(?:lg|xl|2xl|3xl)\b/, `${name}: off-system effect`);
        assert.doesNotMatch(source, /text-(?:xs|sm|base|lg|xl)\b|text-\[\d/, `${name}: off-scale text size`);

        for (const [, rawToken] of source.matchAll(colorUtil)) {
            // border-t-transparent / border-x-line: drop the side prefix.
            const token = rawToken.replace(/^[tblrxy]-/, "");
            if (NON_COLOR.has(token) || /^\d/.test(token)) {
                continue;
            }
            assert.ok(
                STYLE_CSS.includes(`--color-${token}:`),
                `${name}: "${token}" is not a Phase 1 color token`,
            );
        }
    }
});
