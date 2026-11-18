<script setup>
import { ToastClose, ToastDescription, ToastProvider, ToastRoot, ToastTitle, ToastViewport } from "reka-ui";

import { dismissToast, toasts } from "../../services/toast";
import Icon from "./Icon.vue";

// Renders the app-wide toast queue (services/toast.js). Mount once.
// Bottom-right on desktop, full-width above the bottom tab bar on
// mobile. F8 moves focus to the notifications (Reka hotkey).

const TONE_ICON = { success: "check", warning: "warning", error: "error", neutral: "info" };
const TONE_CLASS = {
    success: "text-forest",
    warning: "text-warn-ink",
    error: "text-danger",
    neutral: "text-ink-muted",
};

function onOpenChange(id, open) {
    if (!open) {
        dismissToast(id);
    }
}
</script>

<template>
    <ToastProvider swipe-direction="right">

        <ToastRoot v-for="item in toasts.items" :key="item.id" :duration="item.duration" default-open
            class="flex items-start gap-3 rounded-panel border border-line bg-surface px-4 py-3 text-ink shadow-overlay data-[state=open]:animate-pop-in"
            @update:open="(open) => onOpenChange(item.id, open)">

            <Icon :name="TONE_ICON[item.tone] || 'info'" :size="16" class="mt-0.5"
                :class="TONE_CLASS[item.tone] || TONE_CLASS.neutral" />

            <div class="min-w-0 flex-1">
                <ToastTitle class="text-data font-semibold">{{ item.title }}</ToastTitle>
                <ToastDescription v-if="item.description" class="mt-0.5 text-caption text-ink-muted">
                    {{ item.description }}
                </ToastDescription>
            </div>

            <ToastClose aria-label="Dismiss notification"
                class="grid h-6 w-6 shrink-0 place-items-center rounded-control text-ink-muted transition-colors hover:bg-sunken hover:text-ink">
                <Icon name="x" :size="14" />
            </ToastClose>

        </ToastRoot>

        <ToastViewport
            class="fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2 outline-none max-[767px]:bottom-[72px] max-[767px]:left-4" />

    </ToastProvider>
</template>
