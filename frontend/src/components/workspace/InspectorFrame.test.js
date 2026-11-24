// Run with: node --test src/components/workspace/InspectorFrame.test.js
// Built-in node:test - no test framework dependency. InspectorFrame.vue is
// compiled by Vite's SSR module loader and rendered with Vue's server
// renderer, the same approach as src/components/ui/ui.test.js.
//
// Regression: Reka's SplitterPanel renders an inline `overflow: hidden`,
// which overrides any overflow class put on the panel itself, so the
// docked canvas could not scroll. The scroll container must be an inner
// wrapper around the canvas slot.
import test, { after, before } from "node:test";
import assert from "node:assert/strict";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import vue from "@vitejs/plugin-vue";
import { createServer } from "vite";
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCROLL_CLASSES = ["h-full", "overflow-y-auto", "[scrollbar-width:thin]"];

let server;
let InspectorFrame;

before(async () => {
    server = await createServer({
        configFile: false,
        root: join(HERE, "..", "..", ".."),
        logLevel: "silent",
        plugins: [vue()],
        server: { middlewareMode: true, hmr: false },
        appType: "custom",
    });
    InspectorFrame = (await server.ssrLoadModule("/src/components/workspace/InspectorFrame.vue")).default;
});

after(async () => {
    await server?.close();
});

async function render(props) {
    const app = createSSRApp({
        render: () => h(InspectorFrame, { storageKey: "test-frame", ...props }, {
            default: () => h("p", { id: "canvas-content" }, "canvas"),
            inspector: () => h("p", "inspector"),
        }),
    });
    return renderToString(app);
}

// The opening tag of the canvas SplitterPanel and of the element right
// inside it (the scroll wrapper).
function canvasTags(html) {
    const panel = html.match(/<div[^>]*\bid="canvas"[^>]*>/);
    assert.ok(panel, `canvas SplitterPanel not rendered:\n${html}`);
    const rest = html.slice(panel.index + panel[0].length);
    const wrapper = rest.match(/^\s*(?:<!--[^]*?-->\s*)*(<div[^>]*>)/);
    assert.ok(wrapper, `no element directly inside the canvas panel:\n${rest}`);
    return { panel: panel[0], wrapper: wrapper[1] };
}

const classesOf = (tag) => (tag.match(/\bclass="([^"]*)"/)?.[1] ?? "").split(/\s+/).filter(Boolean);

test("docked: the inner wrapper scrolls, not the SplitterPanel", async () => {
    const html = await render({ stacked: false });
    const { panel, wrapper } = canvasTags(html);

    // Reka's inline overflow:hidden is still on the panel - the reason
    // the scroll has to live one level down.
    assert.match(panel, /overflow:\s*hidden/);
    assert.ok(!classesOf(panel).includes("overflow-y-auto"), `panel must not carry overflow-y-auto: ${panel}`);
    assert.ok(classesOf(panel).includes("h-full"), "panel keeps its full height");

    assert.match(wrapper, /data-canvas-scroll/);
    for (const cls of SCROLL_CLASSES) {
        assert.ok(classesOf(wrapper).includes(cls), `wrapper missing ${cls}: ${wrapper}`);
    }
    // The slot content lives inside the wrapper.
    assert.ok(html.indexOf("canvas-content") > html.indexOf("data-canvas-scroll"));
});

test("stacked: no fixed-height scroll container on the canvas", async () => {
    const html = await render({ stacked: true });
    const { panel, wrapper } = canvasTags(html);

    assert.match(wrapper, /data-canvas-scroll/);
    for (const cls of SCROLL_CLASSES) {
        assert.ok(!classesOf(wrapper).includes(cls), `stacked wrapper must not have ${cls}: ${wrapper}`);
        assert.ok(!classesOf(panel).includes(cls), `stacked panel must not have ${cls}: ${panel}`);
    }
    // Stacked inspector renders below the splitter, unscrolled by the frame.
    assert.match(html, /<aside[^>]*aria-label="Inspector"/);
});
