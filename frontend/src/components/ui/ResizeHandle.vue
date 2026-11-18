<script setup>
import { onMounted, ref } from "vue";
import { SplitterResizeHandle } from "reka-ui";

// =========================================================
// RESIZE HANDLE (Reka Splitter)
// =========================================================
//
// The divider between two SplitterPanels (library | canvas | inspector).
// Visually a 1px hairline; the hit area is 8px wide, and a grip appears
// on hover/focus. Keyboard: focus it and use the arrow keys (Reka's
// window-splitter pattern, role="separator" with aria-valuenow).
//
// Keyboard workaround (verified in a real browser, Reka 2.11): Reka
// attaches the separator's keydown listener in an effect that looks the
// handle up inside the group element once; if the handle isn't there at
// that moment, the effect bails out and is never re-run, so arrow keys
// do nothing (mouse dragging, which looks the handle up at drag time,
// still works). Starting `disabled` and enabling after mount changes a
// dependency of that effect, re-running it when the handle is in place.

defineProps({
    // Accessible name, e.g. "Resize findings inspector".
    label: {
        type: String,
        required: true,
    },
});

const mounted = ref(false);

onMounted(() => {
    mounted.value = true;
});
</script>

<template>
    <SplitterResizeHandle :aria-label="label" :disabled="!mounted"
        class="group relative w-2 shrink-0 cursor-col-resize outline-none before:absolute before:inset-y-0 before:left-1/2 before:w-px before:-translate-x-1/2 before:bg-line before:transition-colors hover:before:bg-forest/40 focus-visible:before:w-0.5 focus-visible:before:bg-forest data-[state=drag]:before:bg-forest">
        <span aria-hidden="true"
            class="absolute left-1/2 top-1/2 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-line-strong opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100"></span>
    </SplitterResizeHandle>
</template>
