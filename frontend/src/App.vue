<script setup>
import { computed, onMounted } from "vue";

import AuthScreen from "./components/AuthScreen.vue";
import Dashboard from "./components/Dashboard.vue";
import { authStore, resolveAppView } from "./services/auth.js";

const auth = authStore.state;

// "loading" until the session check settles, so no protected content
// (or any dashboard request) exists before authentication is known.
const view = computed(() => resolveAppView(auth));

onMounted(() => {
    authStore.restoreSession();
});
</script>

<template>
    <div v-if="view === 'loading'" role="status" aria-live="polite"
        class="flex min-h-screen items-center justify-center bg-[#f6f7fb]">
        <div class="flex items-center gap-3 text-[12px] font-medium text-slate-500">
            <span class="h-4 w-4 animate-spin rounded-full border-2 border-violet-200 border-t-violet-600"
                aria-hidden="true"></span>
            Checking your session…
        </div>
    </div>

    <AuthScreen v-else-if="view === 'auth'" />

    <!-- Keyed by user id: signing out (or in as someone else) unmounts
         the whole dashboard, discarding every component's dataset,
         selection and follow-up state. -->
    <Dashboard v-else :key="auth.user.id" :user="auth.user" :signing-out="auth.pending"
        @logout="authStore.logout()" />
</template>
