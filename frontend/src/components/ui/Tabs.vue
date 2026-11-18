<script setup>
import { TabsRoot } from "reka-ui";

import TabNav from "./TabNav.vue";

// =========================================================
// TABS (Reka UI)
// =========================================================
//
// Accessible tablist: arrow keys / Home / End move between tabs
// (roving tabindex), aria-selected and aria-controls are managed by Reka.
//
// Panels go in the default slot as <TabPanel> and are NEVER unmounted
// when hidden (unmount-on-hide=false): inactive panels keep their
// component state, so leaving Analyze for Schema and coming back keeps
// the current analysis result and follow-up context.
//
// `variant` only restyles the SAME tablist: "top" is the desktop tab
// bar, "bottom" pins it to the bottom of the viewport as the mobile
// navigation. Because the elements never change, switching variant on
// a breakpoint change never remounts the panels.
//
// variant "none" renders no tablist here: the caller places a <TabNav>
// somewhere inside the default slot instead (the workspace shell puts it
// in the sidebar). `orientation` is passed to Reka so arrow keys match
// the list's direction.
//
// The `#end` slot puts actions at the right end of the top tab bar.
// Attributes (e.g. class) apply to the root element, which wraps both
// the tab bar and the panels.

defineProps({
    modelValue: {
        type: String,
        required: true,
    },
    // [{ value, label, icon? }]
    items: {
        type: Array,
        required: true,
    },
    // Accessible name for the tablist.
    label: {
        type: String,
        required: true,
    },
    variant: {
        type: String,
        default: "top",
        validator: (value) => ["top", "bottom", "none"].includes(value),
    },
    orientation: {
        type: String,
        default: "horizontal",
        validator: (value) => ["horizontal", "vertical"].includes(value),
    },
});

const emit = defineEmits(["update:modelValue"]);
</script>

<template>
    <TabsRoot :model-value="modelValue" :unmount-on-hide="false" activation-mode="automatic"
        :orientation="orientation" @update:model-value="(value) => emit('update:modelValue', value)">

        <div v-if="variant !== 'none'" :class="variant === 'bottom'
            ? 'fixed inset-x-0 bottom-0 z-40 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]'
            : 'flex shrink-0 items-center justify-between gap-3 border-b border-line px-4 sm:px-6'">

            <TabNav :items="items" :label="label" :variant="variant" />

            <div v-if="$slots.end && variant === 'top'" class="flex shrink-0 items-center gap-1">
                <slot name="end" />
            </div>

        </div>

        <slot />

    </TabsRoot>
</template>
