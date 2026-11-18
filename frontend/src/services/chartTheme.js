// =========================================================
// CHART THEME
// =========================================================
//
// The single source of ECharts *presentation*: colors, type, gridlines,
// axes and tooltips. It holds no color values of its own - every color
// and font is read at runtime from the Phase 1 design tokens in
// style.css (CSS custom properties on :root), so the validated chart
// palette lives in exactly one place.
//
// Presentation only: nothing here touches chart data, series values,
// aggregation or NULL handling - those stay in AnalyticsChart.vue.
//
// Categorical order is fixed (chart-1 ... chart-6, validated for
// colorblind separation and >= 3:1 contrast on `surface`); ECharts
// assigns it in order and never generates new hues.
//
// Outside a browser (SSR, unit tests) there is no computed style: the
// theme then returns empty values and ECharts falls back to its own
// defaults rather than this module inventing colors.

const CATEGORICAL_TOKENS = [1, 2, 3, 4, 5, 6].map((step) => `--color-chart-${step}`);

// Ranked single-series bars (Analyze): darkest = largest value.
const RANK_TOKENS = [1, 2, 3, 4, 5].map((step) => `--color-rank-${step}`);

const TOKENS = {
    ink: "--color-ink",
    inkMuted: "--color-ink-muted",
    line: "--color-line",
    lineStrong: "--color-line-strong",
    surface: "--color-surface",
    sunken: "--color-sunken",
    canvas: "--color-canvas",
    forest: "--color-forest",
    fontSans: "--font-sans",
    fontMono: "--font-mono",
};

export function readToken(name) {
    if (typeof window === "undefined" || typeof document === "undefined") {
        return "";
    }

    return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// "#183d30" + 0.12 -> "rgba(24, 61, 48, 0.12)". Derives translucent
// variants from a token instead of hard-coding them.
export function withAlpha(hex, alpha) {
    const match = /^#?([0-9a-f]{6})$/i.exec(String(hex || "").trim());

    if (!match) {
        return "";
    }

    const value = parseInt(match[1], 16);
    return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

let cachedTheme = null;

// Tokens are static for the page's lifetime, so they are read once; an
// unresolved read (no DOM yet) is never cached.
export function getChartTheme() {
    if (cachedTheme) {
        return cachedTheme;
    }

    const palette = CATEGORICAL_TOKENS.map(readToken).filter(Boolean);
    const tokens = Object.fromEntries(
        Object.entries(TOKENS).map(([key, name]) => [key, readToken(name)]),
    );

    const rankRamp = RANK_TOKENS.map(readToken).filter(Boolean);
    const theme = { palette, rankRamp, ...tokens };

    if (palette.length === CATEGORICAL_TOKENS.length && tokens.ink) {
        cachedTheme = theme;
    }

    return theme;
}

// ---------------------------------------------------------
// Option fragments (merged into AnalyticsChart's options)
// ---------------------------------------------------------

export function baseTextStyle(theme = getChartTheme()) {
    return {
        fontFamily: theme.fontSans || undefined,
        color: theme.ink || undefined,
    };
}

export function tooltipStyle(theme = getChartTheme()) {
    const shadow = withAlpha(theme.forest, 0.35);

    return {
        backgroundColor: theme.forest || undefined,
        borderWidth: 0,
        borderRadius: 6,
        padding: [8, 11],
        textStyle: {
            color: theme.canvas || undefined,
            fontSize: 12,
            fontFamily: theme.fontSans || undefined,
        },
        extraCssText: shadow ? `box-shadow: 0 12px 32px -8px ${shadow};` : "",
    };
}

export function axisLabelStyle(theme = getChartTheme()) {
    return {
        color: theme.inkMuted || undefined,
        fontSize: 11,
        fontFamily: theme.fontSans || undefined,
    };
}

export function axisLineStyle(theme = getChartTheme()) {
    return { lineStyle: { color: theme.lineStrong || undefined } };
}

export function splitLineStyle(theme = getChartTheme()) {
    // Solid, faint gridlines (visual reference).
    return { lineStyle: { color: theme.line || undefined, type: "solid", opacity: 0.7 } };
}

export function legendTextStyle(theme = getChartTheme()) {
    return {
        color: theme.inkMuted || undefined,
        fontSize: 11,
        fontFamily: theme.fontSans || undefined,
    };
}

// Emphasis halo for hovered marks, derived from the forest token.
export function emphasisShadow(theme = getChartTheme()) {
    return withAlpha(theme.forest, 0.18) || undefined;
}

export function dataZoomSliderStyle(theme = getChartTheme()) {
    return {
        borderColor: theme.line || undefined,
        backgroundColor: theme.sunken || undefined,
        fillerColor: withAlpha(theme.forest, 0.12) || undefined,
        handleStyle: { color: theme.forest || undefined },
        textStyle: { color: theme.inkMuted || undefined, fontSize: 10 },
    };
}
