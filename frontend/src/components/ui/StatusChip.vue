<script setup>
import { computed } from "vue";

import Icon from "./Icon.vue";

// =========================================================
// STATUS CHIP
// =========================================================
//
// A compact state indicator. Meaning never relies on color alone: every
// tone has its own icon shape AND the label is always visible text. The
// only fully rounded element in the system, by design.
//
// Contrast (text on its own fill), all >= 4.5:1 (WCAG AA):
//   success forest/forest-soft ~9.9   warning warn-ink/warn-soft ~5.2
//   error danger/danger-soft ~5.1     neutral ink-muted/sunken ~4.6
//
// The chip is static text. If a status changes while the user watches,
// wrap the chip's container in an aria-live region at the call site.

const props = defineProps({
    tone: {
        type: String,
        default: "neutral",
        validator: (value) => ["success", "warning", "error", "neutral"].includes(value),
    },
    label: {
        type: String,
        required: true,
    },
});

const TONES = {
    success: { classes: "bg-forest-soft text-forest", icon: "check" },
    warning: { classes: "bg-warn-soft text-warn-ink", icon: "warning" },
    error: { classes: "bg-danger-soft text-danger", icon: "error" },
    neutral: { classes: "bg-sunken text-ink-muted", icon: "" },
};

const tone = computed(() => TONES[props.tone] || TONES.neutral);
</script>

<template>
    <span class="inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-0.5 text-caption font-medium"
        :class="tone.classes">

        <Icon v-if="tone.icon" :name="tone.icon" :size="14" />

        <span v-else aria-hidden="true" class="h-1.5 w-1.5 shrink-0 rounded-full bg-current"></span>

        <span class="truncate">{{ label }}</span>

    </span>
</template>
