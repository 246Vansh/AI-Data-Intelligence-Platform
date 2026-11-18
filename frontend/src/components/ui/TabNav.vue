<script setup>
import { TabsList, TabsTrigger } from "reka-ui";

import Icon from "./Icon.vue";

// =========================================================
// TAB NAV (the tablist of a <Tabs> root)
// =========================================================
//
// The Reka tablist + triggers, separated from <Tabs> so the list can sit
// anywhere inside the Tabs root: the workspace shell puts it in the
// forest sidebar (desktop) or a bottom bar (mobile) while the panels
// stay in the workspace. Panels never move, so switching between these
// placements on a breakpoint change never remounts them.
//
// Variants:
//   top     - underline tab bar on ivory (in-panel tabs)
//   bottom  - fixed mobile bottom navigation on ivory
//   sidebar - vertical navigation on forest (use orientation="vertical"
//             on the Tabs root so Up/Down arrows move between items)

defineProps({
    // [{ value, label, icon? }]
    items: { type: Array, required: true },
    // Accessible name for the tablist.
    label: { type: String, required: true },
    variant: {
        type: String,
        default: "top",
        validator: (value) => ["top", "bottom", "sidebar"].includes(value),
    },
});

const LIST = {
    top: "-mb-px flex min-w-0 items-stretch gap-1 overflow-x-auto [scrollbar-width:none]",
    bottom: "grid w-full",
    sidebar: "flex flex-col gap-1",
};

const TRIGGER = {
    top: "relative flex h-10 shrink-0 items-center gap-2 whitespace-nowrap border-b-2 border-transparent px-3 text-data font-medium text-ink-muted transition-colors duration-150 hover:text-ink data-[state=active]:border-forest data-[state=active]:text-ink",
    bottom: "relative flex h-16 flex-col items-center justify-center gap-1 text-data font-medium text-ink-muted transition-colors duration-150 data-[state=active]:font-semibold data-[state=active]:text-ink",
    sidebar: "group/nav relative flex h-11 w-full items-center gap-3 rounded-[10px] px-3.5 text-body font-medium text-on-forest/90 transition-colors duration-150 hover:bg-forest-hover hover:text-on-forest data-[state=active]:bg-forest-active data-[state=active]:font-semibold data-[state=active]:text-on-forest data-[state=active]:shadow-[inset_0_1px_0_rgb(255_255_255/0.08),0_1px_2px_rgb(0_0_0/0.2)]",
};
</script>

<template>
    <TabsList :aria-label="label" :class="LIST[variant]"
        :style="variant === 'bottom' ? { gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` } : undefined">

        <TabsTrigger v-for="item in items" :key="item.value" :value="item.value" :class="TRIGGER[variant]">
            <Icon v-if="item.icon" :name="item.icon" :size="variant === 'top' ? 16 : 20" />
            {{ item.label }}
        </TabsTrigger>

    </TabsList>
</template>
