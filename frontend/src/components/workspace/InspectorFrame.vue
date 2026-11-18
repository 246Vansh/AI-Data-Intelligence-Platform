<script setup>
import { SplitterGroup, SplitterPanel } from "reka-ui";
import { useElementSize } from "@vueuse/core";
import { ref, useSlots, watch } from "vue";

import { splitterStorage } from "../../composables/useUiPreference";
import ResizeHandle from "../ui/ResizeHandle.vue";

// =========================================================
// INSPECTOR FRAME
// =========================================================
//
// Canvas + contextual inspector, side by side and resizable (Reka
// Splitter; the inspector width is remembered per `storageKey`). The
// inspector exists only when an #inspector slot is provided.
//
// The canvas (default slot) ALWAYS renders in the same place - the
// first panel of the same SplitterGroup - whether the inspector is
// docked, `stacked` below (narrow screens), `collapsed`, or absent.
// Only the inspector moves. So a breakpoint change, collapsing the
// inspector or a result appearing never remounts the canvas, i.e. never
// destroys an analysis living in it.
//
// Docked, both panes fill the frame's height and scroll independently.

defineProps({
    storageKey: { type: String, required: true },
    inspectorLabel: { type: String, default: "Inspector" },
    stacked: { type: Boolean, default: false },
    collapsed: { type: Boolean, default: false },
    // No divider or tinted pane: the inspector content sits directly on
    // the canvas (Analyze draws its own cards there).
    bare: { type: Boolean, default: false },
    // Docked width in px (min/max stay 280-480).
    defaultSize: { type: Number, default: 360 },
});

const slots = useSlots();

// The docked inspector is a px-sized Reka panel; Reka converts px to a
// share of the group width when the panel registers. Inside a hidden
// workspace tab (display: none) that width is 0 and the conversion
// breaks (found in browser validation: a 360px inspector came back
// 884px wide). So it is first mounted once the frame has a width, and
// then kept mounted - hiding the tab later must not reset a width the
// user dragged to. The canvas panel is unaffected and never remounts.
const frame = ref(null);
const { width: frameWidth } = useElementSize(frame);
const laidOut = ref(false);
watch(frameWidth, (width) => {
    if (width > 0) laidOut.value = true;
}, { immediate: true });
</script>

<template>
    <div ref="frame" class="flex min-h-0 flex-col" :class="stacked ? '' : 'h-full'">

        <!-- keyboard-resize-by: arrow-key step in % of the group. Reka
             rejects (rather than clamps) a keyboard step that would cross
             a size limit; its default 10% exceeds the inspector's
             280-480px range. -->
        <SplitterGroup direction="horizontal" :auto-save-id="storageKey" :storage="splitterStorage"
            :keyboard-resize-by="1" :class="stacked ? '' : 'min-h-0 flex-1'">

            <SplitterPanel id="canvas" key="canvas" :order="1" :min-size="45" class="min-w-0"
                :class="stacked ? '' : 'h-full overflow-y-auto [scrollbar-width:thin]'">
                <slot />
            </SplitterPanel>

            <template v-if="slots.inspector && !stacked && !collapsed && laidOut">
                <ResizeHandle :label="`Resize ${inspectorLabel.toLowerCase()}`" :class="bare ? 'opacity-0 hover:opacity-100 focus-visible:opacity-100' : ''" />
                <SplitterPanel id="inspector" key="inspector" :order="2" size-unit="px" :default-size="defaultSize"
                    :min-size="280" :max-size="480" class="min-w-0"
                    :class="bare ? '' : 'border-l border-line bg-surface/60'">
                    <aside :aria-label="inspectorLabel" class="h-full overflow-y-auto [scrollbar-width:thin]">
                        <slot name="inspector" />
                    </aside>
                </SplitterPanel>
            </template>

        </SplitterGroup>

        <aside v-if="slots.inspector && stacked" :aria-label="inspectorLabel" :class="bare ? '' : 'border-t border-line'">
            <slot name="inspector" />
        </aside>

    </div>
</template>
