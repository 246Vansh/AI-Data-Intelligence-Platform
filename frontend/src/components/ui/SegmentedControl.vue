<script setup>
import { ToggleGroupItem, ToggleGroupRoot } from "reka-ui";

import Icon from "./Icon.vue";

// =========================================================
// SEGMENTED CONTROL (Reka ToggleGroup, single)
// =========================================================
//
// Switches between views of the same content (Chart | Table, issue
// filters). Arrow keys move between options (roving focus). Exactly one
// option is always selected: clicking the active option does not clear
// it (an empty value is ignored).
//
// items: [{ value, label, icon? }]

defineProps({
    modelValue: {
        type: String,
        required: true,
    },
    items: {
        type: Array,
        required: true,
    },
    label: {
        type: String,
        required: true,
    },
    size: {
        type: String,
        default: "md",
        validator: (value) => ["sm", "md"].includes(value),
    },
});

const emit = defineEmits(["update:modelValue"]);

function onUpdate(value) {
    if (value) {
        emit("update:modelValue", value);
    }
}
</script>

<template>
    <ToggleGroupRoot type="single" :model-value="modelValue" :aria-label="label"
        class="inline-flex items-center gap-0.5 rounded-control bg-sunken p-0.5" @update:model-value="onUpdate">
        <ToggleGroupItem v-for="item in items" :key="item.value" :value="item.value"
            class="inline-flex items-center gap-1.5 rounded-[4px] font-medium text-ink-muted transition-colors duration-150 hover:text-ink data-[state=on]:bg-surface data-[state=on]:text-ink data-[state=on]:shadow-panel"
            :class="size === 'sm' ? 'h-7 px-2.5 text-caption' : 'h-8 px-3 text-data'">
            <Icon v-if="item.icon" :name="item.icon" :size="size === 'sm' ? 14 : 16" />
            {{ item.label }}
        </ToggleGroupItem>
    </ToggleGroupRoot>
</template>
