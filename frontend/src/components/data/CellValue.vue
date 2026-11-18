<script setup>
import { computed } from "vue";

import { isEmptyString, isMissing } from "../../services/columnInsight";

// One preview value. Missing (null) and blank text are shown as quiet
// mono tokens rather than a dash, so "no value" and "an empty string"
// stay distinguishable; numbers keep the preview's existing formatting
// (grouped, at most 2 decimals).

const props = defineProps({
    value: { default: null },
    kind: { type: String, default: "text" },
});

const missing = computed(() => isMissing(props.value));
const empty = computed(() => isEmptyString(props.value));

const NUMBER_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

const text = computed(() => {
    if (typeof props.value === "number") return NUMBER_FORMAT.format(props.value);
    if (typeof props.value === "boolean") return String(props.value);
    if (props.value !== null && typeof props.value === "object") return JSON.stringify(props.value);
    return String(props.value);
});
</script>

<template>
    <span v-if="missing" class="font-mono text-caption italic text-ink-muted/70" title="Missing value (null)">null</span>
    <span v-else-if="empty" class="font-mono text-caption italic text-ink-muted/70" title="Empty text">empty</span>
    <span v-else-if="typeof value === 'boolean'" class="font-mono text-caption text-ink">{{ text }}</span>
    <span v-else :title="text.length > 12 ? text : undefined">{{ text }}</span>
</template>
