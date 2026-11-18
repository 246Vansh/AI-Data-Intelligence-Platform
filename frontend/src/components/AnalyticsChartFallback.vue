<script setup>
import Icon from "./ui/Icon.vue";

// Shown in place of AnalyticsChart while its code (ECharts) is being
// fetched - it is lazy-loaded so the first screen doesn't download the
// charting library - or if that download fails (e.g. offline, or a new
// deploy replaced the chunk). The analysis result itself is unaffected:
// insights, explanation and table still render.

defineProps({
    state: {
        type: String,
        default: "loading",
        validator: (value) => ["loading", "error"].includes(value),
    },
});
</script>

<template>
    <div class="grid h-[440px] place-items-center rounded-panel border border-line bg-surface max-[700px]:h-[390px] max-[450px]:h-[330px]"
        :role="state === 'error' ? 'alert' : 'status'">
        <p v-if="state === 'loading'" class="flex items-center gap-2.5 text-data text-ink-muted">
            <span aria-hidden="true"
                class="h-4 w-4 animate-spin rounded-full border-[1.5px] border-forest/25 border-t-forest"></span>
            Loading chart…
        </p>
        <p v-else class="flex max-w-sm items-start gap-2.5 px-6 text-data text-ink-muted">
            <Icon name="error" :size="16" class="mt-0.5 text-danger" />
            <span>The chart couldn't be loaded. Reload the page to try again; the result's insights and data are
                unaffected.</span>
        </p>
    </div>
</template>
