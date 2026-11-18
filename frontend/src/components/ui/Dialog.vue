<script setup>
import { computed } from "vue";
import {
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogOverlay,
    DialogPortal,
    DialogRoot,
    DialogTitle,
} from "reka-ui";

import { cn } from "../../lib/cn";
import Icon from "./Icon.vue";

// =========================================================
// DIALOG / SHEET (Reka UI)
// =========================================================
//
// One primitive for centered dialogs and edge sheets (`side`). Reka
// provides the accessibility contract: focus moves into the dialog and
// is trapped there, Esc and outside-click close it, page scroll is
// locked, the rest of the page is hidden from assistive tech, and focus
// returns to the element that opened it.
//
// `title` is required - it names the dialog (aria-labelledby). Use
// `hideTitle` only when the content already shows an equivalent visible
// heading; the title is then kept for screen readers.
//
// Motion is a single short entry keyframe per variant (style.css),
// disabled by the global reduced-motion rule. Exit is instant.

const props = defineProps({
    open: {
        type: Boolean,
        default: false,
    },
    title: {
        type: String,
        required: true,
    },
    description: {
        type: String,
        default: "",
    },
    hideTitle: {
        type: Boolean,
        default: false,
    },
    side: {
        type: String,
        default: "center",
        validator: (value) => ["center", "right", "left", "bottom"].includes(value),
    },
    // Width for center/left/right; ignored for bottom sheets (full width).
    width: {
        type: String,
        default: "",
    },
    // Extra classes for the dialog surface (merged with cn()).
    contentClass: {
        type: [String, Array, Object],
        default: "",
    },
    // Extra classes for the scrolling body (merged with cn(), so e.g.
    // "p-0" replaces the default padding for edge-to-edge content).
    bodyClass: {
        type: [String, Array, Object],
        default: "",
    },
    // "forest": the surface is a forest-world panel (mobile navigation
    // drawer) - the close control switches to on-forest colors.
    tone: {
        type: String,
        default: "ivory",
        validator: (value) => ["ivory", "forest"].includes(value),
    },
});

const emit = defineEmits(["update:open"]);

const SIDES = {
    center: "left-1/2 top-[12vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 rounded-panel data-[state=open]:animate-dialog-in",
    right: "inset-y-0 right-0 h-full w-[min(92vw,420px)] border-l data-[state=open]:animate-sheet-in-right",
    left: "inset-y-0 left-0 h-full w-[min(92vw,320px)] border-r data-[state=open]:animate-sheet-in-left",
    // The safe-area bottom padding keeps the sheet's last row above the iOS home
    // indicator / Android gesture bar (0 on devices without one).
    bottom: "inset-x-0 bottom-0 max-h-[88vh] w-full rounded-t-panel border-t pb-[env(safe-area-inset-bottom)] data-[state=open]:animate-sheet-in-bottom",
};

const contentClass = computed(() =>
    cn(
        "fixed z-50 flex flex-col border-line bg-surface text-ink shadow-overlay focus-visible:outline-none",
        props.side === "center" ? "border" : "",
        SIDES[props.side],
        props.width,
        props.tone === "forest" ? "theme-forest border-forest-line bg-forest text-on-forest" : "",
        props.contentClass,
    ),
);

const bodyClass = computed(() =>
    cn("min-h-0 flex-1 overflow-y-auto px-5 pb-5", props.hideTitle ? "pt-12" : "", props.bodyClass),
);

const closeClass = computed(() =>
    props.tone === "forest"
        ? "text-on-forest-muted hover:bg-forest-hover hover:text-on-forest"
        : "text-ink-muted hover:bg-sunken hover:text-ink",
);
</script>

<template>
    <DialogRoot :open="open" @update:open="(value) => emit('update:open', value)">

        <slot name="trigger" />

        <DialogPortal>

            <DialogOverlay class="fixed inset-0 z-50 bg-ink/30 data-[state=open]:animate-overlay-in" />

            <DialogContent :class="contentClass">

                <!-- Bottom-sheet grabber (visual affordance only) -->
                <span v-if="side === 'bottom'" aria-hidden="true"
                    class="mx-auto mt-2 h-1 w-10 shrink-0 rounded-full bg-line-strong"></span>

                <header class="flex items-start justify-between gap-4 px-5 pb-3 pt-4"
                    :class="hideTitle ? 'sr-only' : ''">
                    <div class="min-w-0">
                        <DialogTitle class="text-lead font-semibold text-ink">
                            {{ title }}
                        </DialogTitle>
                        <DialogDescription v-if="description" class="mt-0.5 text-data text-ink-muted">
                            {{ description }}
                        </DialogDescription>
                    </div>
                </header>

                <DialogClose aria-label="Close"
                    class="absolute right-3 top-3 z-10 grid h-8 w-8 place-items-center rounded-control transition-colors duration-150"
                    :class="closeClass">
                    <Icon name="x" :size="16" />
                </DialogClose>

                <!-- With a visually hidden title the absolutely positioned
                     Close button would sit on the content's top-right
                     corner (found in browser validation: it covered the
                     library's mode toggle) - reserve its 48px row. -->
                <div :class="bodyClass">
                    <slot />
                </div>

                <footer v-if="$slots.footer"
                    class="flex items-center justify-end gap-2 border-t border-line px-5 py-3">
                    <slot name="footer" />
                </footer>

            </DialogContent>

        </DialogPortal>

    </DialogRoot>
</template>
