<script setup>
import {
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuPortal,
    DropdownMenuRoot,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "reka-ui";

import Icon from "./Icon.vue";

// =========================================================
// MENU (Reka DropdownMenu)
// =========================================================
//
// For small action lists (dataset menu, account, row overflow). Reka
// handles arrow-key navigation, typeahead, Esc, focus return and
// collision-aware positioning.
//
// The trigger goes in the `trigger` slot and must be a single focusable
// element (it is rendered with as-child). Items:
//   { key, label, icon?, danger?, disabled? }  or  { separator: true }
// Choosing an item emits `select` with its key.

defineProps({
    items: {
        type: Array,
        required: true,
    },
    align: {
        type: String,
        default: "end",
        validator: (value) => ["start", "center", "end"].includes(value),
    },
    side: {
        type: String,
        default: "bottom",
        validator: (value) => ["top", "right", "bottom", "left"].includes(value),
    },
});

const emit = defineEmits(["select"]);
</script>

<template>
    <DropdownMenuRoot>

        <DropdownMenuTrigger as-child>
            <slot name="trigger" />
        </DropdownMenuTrigger>

        <DropdownMenuPortal>
            <DropdownMenuContent :align="align" :side="side" :side-offset="6" :collision-padding="8"
                class="z-50 min-w-[200px] rounded-panel border border-line bg-surface p-1 text-data text-ink shadow-overlay data-[state=open]:animate-pop-in">

                <template v-for="(item, index) in items" :key="item.key || `separator-${index}`">

                    <DropdownMenuSeparator v-if="item.separator" class="my-1 h-px bg-line" />

                    <DropdownMenuItem v-else :disabled="item.disabled" @select="emit('select', item.key)"
                        class="flex cursor-default select-none items-center gap-2.5 rounded-control px-2.5 py-1.5 outline-none data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
                        :class="item.danger
                            ? 'text-danger data-[highlighted]:bg-danger-soft'
                            : 'data-[highlighted]:bg-sunken'">
                        <Icon v-if="item.icon" :name="item.icon" :size="16"
                            :class="item.danger ? '' : 'text-ink-muted'" />
                        {{ item.label }}
                    </DropdownMenuItem>

                </template>

            </DropdownMenuContent>
        </DropdownMenuPortal>

    </DropdownMenuRoot>
</template>
