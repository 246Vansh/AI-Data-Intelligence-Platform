<script setup>
import { TabsContent } from "reka-ui";

// A tab's content. Always mounted (see Tabs.vue); an inactive panel is
// only hidden, so its components keep their state and in-flight work.

defineProps({
    value: {
        type: String,
        required: true,
    },
});
</script>

<template>
    <TabsContent :value="value" class="min-h-0 data-[state=inactive]:hidden">
        <slot />
    </TabsContent>
</template>
