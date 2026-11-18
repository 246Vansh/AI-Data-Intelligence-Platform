<script setup>
import { computed, useAttrs } from "vue";

import { cn } from "../../lib/cn";
import Icon from "./Icon.vue";

// `class` is merged with cn() (a caller's override wins, e.g. h-11 over
// the default h-9); every other attribute and listener still falls
// through to the native <button> via v-bind="passthrough".
defineOptions({ inheritAttrs: false });

const attrs = useAttrs();

// =========================================================
// BUTTON
// =========================================================
//
// A real <button>: every attribute and listener not declared here
// (onClick, aria-label, title, form, name, ...) falls through to it.
// `type` defaults to "button" so a Button inside a <form> never submits
// by accident; pass type="submit" where submitting is intended.
//
// `loading` disables the button, sets aria-busy and swaps the leading
// icon for a spinner while keeping the label, so the width doesn't jump
// and screen readers still hear what the button does. An icon-only
// button must be given an aria-label.

const props = defineProps({
    variant: {
        type: String,
        default: "secondary",
        validator: (value) => ["primary", "secondary", "danger"].includes(value),
    },
    size: {
        type: String,
        default: "md",
        validator: (value) => ["sm", "md"].includes(value),
    },
    type: {
        type: String,
        default: "button",
        validator: (value) => ["button", "submit", "reset"].includes(value),
    },
    // Leading icon name (see Icon.vue).
    icon: {
        type: String,
        default: "",
    },
    disabled: {
        type: Boolean,
        default: false,
    },
    loading: {
        type: Boolean,
        default: false,
    },
});

const VARIANTS = {
    primary: "border-forest bg-forest text-canvas hover:border-forest-hover hover:bg-forest-hover",
    secondary: "border-line-strong bg-surface text-ink hover:bg-sunken",
    danger: "border-danger bg-danger text-surface hover:brightness-95 focus-visible:outline-danger",
};

const SIZES = {
    sm: "h-8 gap-1.5 px-2.5 text-caption",
    md: "h-9 gap-2 px-3.5 text-data",
};

const isDisabled = computed(() => props.disabled || props.loading);

const BASE =
    "inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap rounded-control border font-medium transition-colors duration-150 ease-out-quiet disabled:cursor-not-allowed disabled:opacity-55";

const classes = computed(() => cn(BASE, VARIANTS[props.variant], SIZES[props.size], attrs.class));

const passthrough = computed(() => {
    const { class: _ignored, ...rest } = attrs;
    return rest;
});
</script>

<template>
    <button v-bind="passthrough" :type="type" :disabled="isDisabled" :aria-busy="loading ? 'true' : undefined"
        :class="classes">

        <span v-if="loading" aria-hidden="true"
            class="h-3.5 w-3.5 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"></span>

        <Icon v-else-if="icon" :name="icon" :size="size === 'sm' ? 14 : 16" />

        <slot />

    </button>
</template>
