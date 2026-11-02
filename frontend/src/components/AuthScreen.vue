<script setup>
import { computed, ref } from "vue";

import {
    MIN_PASSWORD_LENGTH,
    authStore,
    validateEmail,
    validatePassword,
} from "../services/auth.js";

// =========================================================
// STATE
// =========================================================
//
// Credentials live only in these refs while the form is on screen and
// are cleared after each submit; nothing is written to browser storage.

const mode = ref("login");
const email = ref("");
const password = ref("");
const touched = ref({ email: false, password: false });

const auth = authStore.state;

const isRegister = computed(() => mode.value === "register");

const emailError = computed(() =>
    touched.value.email ? validateEmail(email.value) : "",
);

const passwordError = computed(() => {
    if (!touched.value.password) {
        return "";
    }
    // Sign-in only needs a non-empty password: the length rule is a
    // registration policy, and older passwords are judged by the server.
    return isRegister.value
        ? validatePassword(password.value)
        : password.value ? "" : "Enter your password.";
});

const canSubmit = computed(
    () =>
        !auth.pending &&
        !validateEmail(email.value) &&
        (isRegister.value ? !validatePassword(password.value) : Boolean(password.value)),
);

// =========================================================
// ACTIONS
// =========================================================

function switchMode(next) {
    if (auth.pending || mode.value === next) {
        return;
    }
    mode.value = next;
    password.value = "";
    touched.value = { email: false, password: false };
    authStore.clearMessages();
}

async function submit() {
    touched.value = { email: true, password: true };

    if (!canSubmit.value) {
        return;
    }

    const action = isRegister.value ? authStore.register : authStore.login;
    const ok = await action(email.value, password.value);

    password.value = "";
    touched.value = { ...touched.value, password: false };

    if (!ok && auth.notice) {
        // Registered but auto sign-in failed: switch to the sign-in form.
        mode.value = "login";
    }
}
</script>

<template>
    <div class="flex min-h-screen items-center justify-center bg-[#f6f7fb] px-4 py-10 text-[#172033] selection:bg-violet-100 selection:text-violet-800">

        <div class="w-full max-w-[400px]">

            <!-- Brand -->

            <div class="mb-7 flex items-center justify-center gap-3">

                <div
                    class="relative grid h-11 w-11 shrink-0 place-items-center overflow-hidden rounded-xl bg-gradient-to-br from-violet-600 via-indigo-600 to-blue-600 text-lg font-bold text-white shadow-[0_8px_22px_rgba(99,102,241,0.25)]">
                    <span class="relative z-10">✦</span>
                </div>

                <div>
                    <p class="text-[15px] font-bold tracking-[-0.25px] text-slate-900">
                        AI Data Intelligence Platform
                    </p>
                    <p class="mt-0.5 text-[11px] text-slate-400">
                        Interactive data analytics workspace
                    </p>
                </div>

            </div>

            <!-- Card -->

            <div class="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-[0_10px_30px_rgba(15,23,42,0.06)] sm:p-7">

                <div class="mb-6 grid grid-cols-2 gap-1 rounded-xl bg-slate-100 p-1" role="tablist">

                    <button v-for="tab in [{ id: 'login', label: 'Sign in' }, { id: 'register', label: 'Create account' }]"
                        :key="tab.id" type="button" role="tab" :aria-selected="mode === tab.id"
                        :disabled="auth.pending" @click="switchMode(tab.id)" :class="mode === tab.id
                            ? 'bg-white text-slate-900 shadow-sm'
                            : 'text-slate-500 hover:text-slate-700'"
                        class="rounded-lg px-3 py-2 text-[12px] font-semibold transition disabled:cursor-not-allowed">
                        {{ tab.label }}
                    </button>

                </div>

                <h1 class="text-[18px] font-bold tracking-[-0.3px] text-slate-900">
                    {{ isRegister ? 'Create your account' : 'Welcome back' }}
                </h1>
                <p class="mt-1 text-[12px] text-slate-500">
                    {{ isRegister ? 'Register to start analyzing your datasets.' : 'Sign in to access your datasets.' }}
                </p>

                <p v-if="auth.notice" role="status"
                    class="mt-5 rounded-xl border border-emerald-100 bg-emerald-50 px-3.5 py-2.5 text-[12px] font-medium text-emerald-700">
                    {{ auth.notice }}
                </p>

                <p v-if="auth.error" role="alert"
                    class="mt-5 rounded-xl border border-red-100 bg-red-50 px-3.5 py-2.5 text-[12px] font-medium text-red-600">
                    {{ auth.error }}
                </p>

                <form class="mt-5 space-y-4" novalidate @submit.prevent="submit">

                    <div>
                        <label for="auth-email" class="mb-1.5 block text-[11px] font-semibold text-slate-600">
                            Email
                        </label>
                        <input id="auth-email" v-model="email" type="email" autocomplete="username" inputmode="email"
                            maxlength="254" :disabled="auth.pending" :aria-invalid="Boolean(emailError)"
                            aria-describedby="auth-email-error" @blur="touched.email = true"
                            class="w-full rounded-xl border bg-white px-3.5 py-2.5 text-[13px] text-slate-900 outline-none transition placeholder:text-slate-400 focus:ring-4 disabled:bg-slate-50"
                            :class="emailError
                                ? 'border-red-300 focus:border-red-400 focus:ring-red-100'
                                : 'border-slate-200 focus:border-violet-400 focus:ring-violet-100'"
                            placeholder="you@company.com" />
                        <p v-if="emailError" id="auth-email-error" class="mt-1.5 text-[11px] text-red-600">
                            {{ emailError }}
                        </p>
                    </div>

                    <div>
                        <label for="auth-password" class="mb-1.5 block text-[11px] font-semibold text-slate-600">
                            Password
                        </label>
                        <input id="auth-password" v-model="password" type="password"
                            :autocomplete="isRegister ? 'new-password' : 'current-password'" maxlength="256"
                            :disabled="auth.pending" :aria-invalid="Boolean(passwordError)"
                            aria-describedby="auth-password-hint" @blur="touched.password = true"
                            class="w-full rounded-xl border bg-white px-3.5 py-2.5 text-[13px] text-slate-900 outline-none transition focus:ring-4 disabled:bg-slate-50"
                            :class="passwordError
                                ? 'border-red-300 focus:border-red-400 focus:ring-red-100'
                                : 'border-slate-200 focus:border-violet-400 focus:ring-violet-100'" />
                        <p id="auth-password-hint" class="mt-1.5 text-[11px]"
                            :class="passwordError ? 'text-red-600' : 'text-slate-400'">
                            {{ passwordError || (isRegister ? `At least ${MIN_PASSWORD_LENGTH} characters.` : '') }}
                        </p>
                    </div>

                    <button type="submit" :disabled="!canSubmit"
                        class="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-indigo-600 px-4 py-2.5 text-[13px] font-semibold text-white shadow-[0_8px_20px_rgba(99,102,241,0.25)] transition hover:from-violet-700 hover:to-indigo-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-violet-200 disabled:cursor-not-allowed disabled:opacity-60">
                        <span v-if="auth.pending"
                            class="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"
                            aria-hidden="true"></span>
                        {{ auth.pending
                            ? (isRegister ? 'Creating account…' : 'Signing in…')
                            : (isRegister ? 'Create account' : 'Sign in') }}
                    </button>

                </form>

            </div>

        </div>

    </div>
</template>
