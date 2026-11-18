<script setup>
// =========================================================
// FOREST SCENE (decorative)
// =========================================================
//
// The misty pine ridge at the foot of the sidebar in the visual
// reference: three depth layers of hills and pines, darkest in front,
// fading into the sidebar's own green. Pure SVG generated from a few
// tree positions - no image asset. aria-hidden; never interactive.

// One pine: a short trunk and four stacked tiers, narrowing upwards.
function pine(x, base, height) {
    const tiers = 4;
    const points = [];
    const tierHeight = height / (tiers + 0.6);
    for (let i = 0; i < tiers; i += 1) {
        const bottom = base - height * 0.08 - i * tierHeight * 0.82;
        const top = bottom - tierHeight * 1.35;
        const half = (height * 0.26) * (1 - i / (tiers + 0.8));
        points.push(`M${x - half},${bottom} L${x},${top} L${x + half},${bottom} Z`);
    }
    points.push(`M${x - height * 0.025},${base} h${height * 0.05} v${-height * 0.12} h${-height * 0.05} Z`);
    return points.join(" ");
}

const FAR = [[18, 150, 40], [52, 146, 46], [96, 152, 36], [150, 140, 52], [196, 148, 42], [236, 144, 48]];
const MID = [[34, 168, 58], [78, 172, 44], [176, 164, 70], [214, 170, 56], [252, 166, 62]];
const NEAR = [[8, 196, 76], [62, 198, 54], [196, 192, 92], [228, 196, 66]];

const farPath = FAR.map(([x, b, h]) => pine(x, b, h)).join(" ");
const midPath = MID.map(([x, b, h]) => pine(x, b, h)).join(" ");
const nearPath = NEAR.map(([x, b, h]) => pine(x, b, h)).join(" ");
</script>

<template>
    <svg aria-hidden="true" viewBox="0 0 260 200" preserveAspectRatio="xMidYMax slice" class="block h-full w-full">
        <defs>
            <linearGradient id="forest-mist" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#2f5c43" stop-opacity="0" />
                <stop offset="0.55" stop-color="#2f5c43" stop-opacity="0.35" />
                <stop offset="1" stop-color="#2f5c43" stop-opacity="0" />
            </linearGradient>
        </defs>
        <!-- far ridge -->
        <path d="M0 150 C40 124 70 132 104 120 C140 108 170 128 206 116 C230 108 248 114 260 110 V200 H0 Z"
            fill="#2a5540" opacity="0.55" />
        <path :d="farPath" fill="#285239" opacity="0.7" />
        <rect x="0" y="110" width="260" height="70" fill="url(#forest-mist)" />
        <!-- middle ridge -->
        <path d="M0 176 C34 156 70 166 110 154 C150 142 190 160 260 148 V200 H0 Z" fill="#1d4330" opacity="0.85" />
        <path :d="midPath" fill="#1a3e2c" />
        <!-- near ridge -->
        <path d="M0 200 V186 C40 176 90 184 130 178 C170 172 220 184 260 176 V200 Z" fill="#11301f" />
        <path :d="nearPath" fill="#10301f" />
    </svg>
</template>
