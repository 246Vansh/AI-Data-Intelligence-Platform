<script setup>
import { TooltipContent, TooltipPortal, TooltipProvider, TooltipRoot, TooltipTrigger } from "reka-ui";

// =========================================================
// TOOLTIP (Reka UI)
// =========================================================
//
// Supplementary text only (truncated names, shortcut hints) - never the
// sole carrier of information or an icon-only button's name (that is
// the button's aria-label). Opens on hover and keyboard focus; Esc
// dismisses. The trigger (default slot) must be one focusable element.
// Each tooltip carries its own provider, so no app-level setup is
// needed.

defineProps({
    content: {
        type: String,
        required: true,
    },
    side: {
        type: String,
        default: "top",
        validator: (value) => ["top", "right", "bottom", "left"].includes(value),
    },
    delay: {
        type: Number,
        default: 400,
    },
});
</script>

<template>
    <TooltipProvider :delay-duration="delay">
        <TooltipRoot>
            <TooltipTrigger as-child>
                <slot />
            </TooltipTrigger>
            <TooltipPortal>
                <TooltipContent :side="side" :side-offset="6" :collision-padding="8"
                    class="z-50 max-w-xs rounded-control bg-forest px-2.5 py-1.5 text-caption text-canvas shadow-overlay data-[state=delayed-open]:animate-pop-in">
                    {{ content }}
                </TooltipContent>
            </TooltipPortal>
        </TooltipRoot>
    </TooltipProvider>
</template>
