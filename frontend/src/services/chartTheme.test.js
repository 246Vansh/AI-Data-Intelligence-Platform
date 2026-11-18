// Run with: node --test src/services/chartTheme.test.js
// Built-in node:test - no test framework dependency.
import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (path) => fileURLToPath(new URL(path, import.meta.url));
const THEME_SOURCE = readFileSync(here("./chartTheme.js"), "utf8");
const STYLE_CSS = readFileSync(here("../style.css"), "utf8");

// Fake computed style: the values a browser would resolve from style.css.
function tokensFromCss() {
    const values = {};
    for (const [, name, value] of STYLE_CSS.matchAll(/(--[a-z0-9-]+):\s*([^;]+);/g)) {
        values[name] = value.trim();
    }
    return values;
}

function installDom(values) {
    globalThis.window = {
        getComputedStyle: () => ({ getPropertyValue: (name) => values[name] ?? "" }),
    };
    globalThis.document = { documentElement: {} };
}

afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
});

// Fresh module instance per test (the theme caches once resolved).
let importCounter = 0;
const loadTheme = () => import(`./chartTheme.js?fresh=${importCounter++}`);

test("chartTheme holds no color literals of its own", () => {
    const code = THEME_SOURCE.replace(/^\s*\/\/.*$/gm, "");
    assert.doesNotMatch(code, /#[0-9a-fA-F]{3,8}\b/);
    assert.doesNotMatch(code, /\brgba?\(\s*\d/);
});

test("every token chartTheme reads is defined in style.css", () => {
    const names = [...THEME_SOURCE.matchAll(/"(--(?:color|font)-[a-z0-9-]+)"/g)].map((m) => m[1]);
    const chartNames = [1, 2, 3, 4, 5, 6].map((i) => `--color-chart-${i}`);

    for (const name of [...names, ...chartNames]) {
        assert.ok(STYLE_CSS.includes(`${name}:`), `missing token ${name}`);
    }
});

test("chart tokens live in the always-emitted @theme static block", () => {
    const staticBlock = STYLE_CSS.match(/@theme static \{([\s\S]*?)\}/)?.[1] || "";
    for (let i = 1; i <= 6; i += 1) {
        assert.match(staticBlock, new RegExp(`--color-chart-${i}:`));
    }
});

test("palette and styles resolve from the CSS tokens in fixed order", async () => {
    const css = tokensFromCss();
    installDom(css);
    const theme = await loadTheme();

    const resolved = theme.getChartTheme();

    assert.deepEqual(
        resolved.palette,
        [1, 2, 3, 4, 5, 6].map((i) => css[`--color-chart-${i}`]),
    );
    assert.equal(theme.tooltipStyle(resolved).backgroundColor, css["--color-forest"]);
    assert.equal(theme.tooltipStyle(resolved).textStyle.color, css["--color-canvas"]);
    assert.equal(theme.axisLabelStyle(resolved).color, css["--color-ink-muted"]);
    assert.equal(theme.splitLineStyle(resolved).lineStyle.color, css["--color-line"]);
    assert.equal(theme.splitLineStyle(resolved).lineStyle.type, "solid");
    assert.match(theme.baseTextStyle(resolved).fontFamily, /Instrument Sans/);
});

test("translucent variants are derived from tokens", async () => {
    const theme = await loadTheme();

    assert.equal(theme.withAlpha("#183d30", 0.12), "rgba(24, 61, 48, 0.12)");
    assert.equal(theme.withAlpha("not-a-color", 0.5), "");
});

test("outside a browser the theme invents nothing (ECharts defaults apply)", async () => {
    const theme = await loadTheme();
    const resolved = theme.getChartTheme();

    assert.deepEqual(resolved.palette, []);
    assert.equal(theme.tooltipStyle(resolved).backgroundColor, undefined);
    assert.equal(theme.axisLabelStyle(resolved).color, undefined);
});
