import { reactive, readonly } from "vue";

// =========================================================
// TOASTS
// =========================================================
//
// Transient confirmations for actions whose UI closes on success
// ("sales.csv uploaded", "Dataset deleted"). Not for errors the user
// must act on - those stay inline next to the control that failed.
//
// One app-wide queue rendered by ui/Toaster.vue (Reka Toast: polite
// live region, pause on hover/focus, swipe or Esc to dismiss).

const MAX_VISIBLE = 3;

const state = reactive({ items: [] });
let nextId = 1;

export function toast({ title, description = "", tone = "neutral", duration = 5000 }) {
    if (!title) {
        return null;
    }

    const id = nextId++;
    state.items.push({ id, title, description, tone, duration });

    while (state.items.length > MAX_VISIBLE) {
        state.items.shift();
    }

    return id;
}

export function dismissToast(id) {
    const index = state.items.findIndex((item) => item.id === id);
    if (index >= 0) {
        state.items.splice(index, 1);
    }
}

export function clearToasts() {
    state.items.splice(0, state.items.length);
}

export const toasts = readonly(state);
