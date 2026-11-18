<script setup>
import { useSlots } from "vue";

import Icon from "./Icon.vue";

// =========================================================
// EMPTY STATE
// =========================================================
//
// What a panel shows when there is nothing to display yet. Copy should
// direct ("Upload a CSV to see its schema"), not apologize. The action
// slot holds the way forward, typically a <Button>.

defineProps({
    title: {
        type: String,
        required: true,
    },
    description: {
        type: String,
        default: "",
    },
    // Icon name (see Icon.vue); omit for a text-only state.
    icon: {
        type: String,
        default: "",
    },
});

const slots = useSlots();
</script>

<template>
    <div class="flex flex-col items-center px-6 py-10 text-center">

        <div v-if="icon"
            class="mb-3 grid h-10 w-10 place-items-center rounded-control bg-sunken text-ink-muted">
            <Icon :name="icon" :size="20" />
        </div>

        <p class="text-body font-semibold text-ink">
            {{ title }}
        </p>

        <p v-if="description" class="mt-1 max-w-[44ch] text-data text-ink-muted">
            {{ description }}
        </p>

        <div v-if="slots.action" class="mt-4 flex flex-wrap items-center justify-center gap-2">
            <slot name="action" />
        </div>

    </div>
</template>
