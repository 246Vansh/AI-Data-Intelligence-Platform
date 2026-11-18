import { extendTailwindMerge } from "tailwind-merge";

// =========================================================
// cn() - merge class lists, resolving Tailwind conflicts
// =========================================================
//
// Primitives accept a `class` from their parent. Without conflict
// resolution, `h-9` (component default) and `h-11` (override) both
// land on the element and whichever Tailwind emits later wins - the
// bug hit in Phase 6. cn() keeps the LAST conflicting class, so a
// caller's override reliably wins.
//
// tailwind-merge must know the Phase 1 tokens, or it misgroups them:
// `text-data` (a font size) and `text-ink` (a color) share the `text-`
// prefix and would otherwise be treated as two colors, silently
// dropping one. Same for the named radii, shadows and easing.

const twMerge = extendTailwindMerge({
    extend: {
        theme: {
            text: ["caption", "data", "body", "lead", "title", "display"],
            radius: ["control", "panel"],
            shadow: ["panel", "overlay"],
            ease: ["out-quiet"],
        },
    },
});

// Flattens what Vue accepts for `class` (string, array, object map,
// falsy) into one string, then resolves conflicts.
function flatten(value, out) {
    if (!value) {
        return out;
    }
    if (typeof value === "string") {
        out.push(value);
    } else if (Array.isArray(value)) {
        for (const item of value) {
            flatten(item, out);
        }
    } else if (typeof value === "object") {
        for (const [name, enabled] of Object.entries(value)) {
            if (enabled) {
                out.push(name);
            }
        }
    }
    return out;
}

export function cn(...inputs) {
    return twMerge(flatten(inputs, []).join(" "));
}
