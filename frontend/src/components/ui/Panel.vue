<script setup>
import { computed, useId, useSlots } from "vue";

// =========================================================
// PANEL
// =========================================================
//
// The off-white surface every data-bearing section sits on: one radius
// (rounded-panel), one hairline, one quiet elevation (shadow-panel).
// The header renders only when there is a title or actions, so a bare
// <Panel> is just a surface.
//
// `flush` drops the body padding and rules the header off, for content
// that runs edge to edge (tables, charts).
//
// overflow-clip (not overflow-hidden) rounds flush content's corners
// without making the panel a scroll container, so sticky elements
// inside still stick to the page.

const props = defineProps({
    title: {
        type: String,
        default: "",
    },
    description: {
        type: String,
        default: "",
    },
    // Element for the panel itself: "section" (landmark, labelled by
    // its title) or a neutral "div"/"article".
    as: {
        type: String,
        default: "section",
        validator: (value) => ["section", "div", "article"].includes(value),
    },
    // Heading level for the title, so panels fit the page outline.
    headingLevel: {
        type: Number,
        default: 2,
        validator: (value) => value >= 2 && value <= 4,
    },
    flush: {
        type: Boolean,
        default: false,
    },
});

const slots = useSlots();
const titleId = useId();

const hasHeader = computed(() => Boolean(props.title || slots.actions));
const headingTag = computed(() => `h${props.headingLevel}`);
</script>

<template>
    <component :is="as" :aria-labelledby="as === 'section' && title ? titleId : undefined"
        class="min-w-0 overflow-clip rounded-panel border border-line bg-surface shadow-panel">

        <header v-if="hasHeader" class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-5 pt-4"
            :class="flush ? 'border-b border-line pb-3.5' : 'pb-1'">

            <div v-if="title" class="min-w-0">
                <component :is="headingTag" :id="titleId" class="text-lead font-semibold text-ink">
                    {{ title }}
                </component>
                <p v-if="description" class="mt-0.5 text-data text-ink-muted">
                    {{ description }}
                </p>
            </div>

            <div v-if="slots.actions" class="flex shrink-0 items-center gap-2">
                <slot name="actions" />
            </div>

        </header>

        <div :class="flush ? '' : 'px-5 pb-5 pt-4'">
            <slot />
        </div>

        <footer v-if="slots.footer" class="border-t border-line px-5 py-3 text-data text-ink-muted">
            <slot name="footer" />
        </footer>

    </component>
</template>
