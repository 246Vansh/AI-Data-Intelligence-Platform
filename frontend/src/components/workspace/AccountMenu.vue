<script setup>
import { computed } from "vue";

import Menu from "../ui/Menu.vue";

// Account actions for the signed-in user (rail footer on desktop, top
// bar on mobile). Sign out emits `logout` exactly as before; while it is
// running the item is disabled and says so. The trigger is supplied by
// the host (rail icon button / mobile avatar button).

const props = defineProps({
    user: { type: Object, default: null },
    signingOut: { type: Boolean, default: false },
    side: { type: String, default: "right" },
    align: { type: String, default: "end" },
});

const emit = defineEmits(["logout"]);

const items = computed(() => [
    { key: "identity", label: props.user?.email || props.user?.id || "Signed in", icon: "user", disabled: true },
    { separator: true },
    { key: "logout", label: props.signingOut ? "Signing out…" : "Sign out", icon: "log-out", disabled: props.signingOut },
]);

function onSelect(key) {
    if (key === "logout") {
        emit("logout");
    }
}
</script>

<template>
    <Menu :items="items" :side="side" :align="align" @select="onSelect">
        <template #trigger>
            <slot />
        </template>
    </Menu>
</template>
