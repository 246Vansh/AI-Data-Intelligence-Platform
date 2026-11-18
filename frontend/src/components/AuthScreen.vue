<script setup>
import { computed, ref } from "vue";

import {
    MIN_PASSWORD_LENGTH,
    authStore,
    validateEmail,
    validatePassword,
} from "../services/auth.js";
import Button from "./ui/Button.vue";
import Icon from "./ui/Icon.vue";
import BrandMark from "./workspace/BrandMark.vue";

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
// Presentation only: shows the typed password in the field. Reset on
// every mode switch and submit, so it never stays on unexpectedly.
const showPassword = ref(false);

// What the product does - the four workspace sections, as shown in the
// app's own navigation.
const CAPABILITIES = [
    { icon: "sparkle", title: "Analyze", text: "Ask questions in plain language and see how each answer was calculated." },
    { icon: "table", title: "Data", text: "Browse rows and inspect every column." },
    { icon: "columns", title: "Schema", text: "Review types and analytical roles." },
    { icon: "shield-check", title: "Quality", text: "Find missing values, duplicates and outliers." },
];

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
    showPassword.value = false;
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
    showPassword.value = false;
    touched.value = { ...touched.value, password: false };

    if (!ok && auth.notice) {
        // Registered but auto sign-in failed: switch to the sign-in form.
        mode.value = "login";
    }
}
</script>

<template>
    <div class="min-h-dvh bg-canvas text-ink lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,640px)_1fr]">

        <!-- =====================================================
             BRAND PANEL
             Desktop: a full-height forest panel. Mobile: a compact
             forest band above the form. Same surface as the workspace
             sidebar, so signing in already looks like the product.
        ====================================================== -->

        <aside
            class="theme-forest relative overflow-hidden bg-forest text-on-forest lg:flex lg:min-h-dvh lg:flex-col lg:justify-between lg:px-12 lg:py-10 xl:px-16">

            <div aria-hidden="true"
                class="pointer-events-none absolute inset-0 bg-[linear-gradient(160deg,transparent_30%,var(--color-forest-deep)_100%)]">
            </div>

            <!-- Contour lines: a quiet terrain/data motif. Decorative. -->
            <svg aria-hidden="true" viewBox="0 0 600 600" preserveAspectRatio="xMidYMid slice"
                class="pointer-events-none absolute -bottom-24 -right-40 h-[560px] w-[560px] text-forest-line opacity-80 max-lg:-top-40 max-lg:h-[420px] max-lg:w-[420px]"
                fill="none" stroke="currentColor" stroke-width="1.25">
                <path d="M300 90c96 4 190 66 206 168 18 112-60 236-196 246S86 432 82 316 196 86 300 90Z" />
                <path d="M300 140c72 3 146 52 158 128 14 86-46 180-150 188S132 412 128 324s92-186 172-184Z" />
                <path d="M300 190c50 2 100 36 108 90 10 60-32 126-104 132s-128-38-130-100 70-124 126-122Z" />
                <path d="M300 240c30 1 60 22 64 54 6 36-20 76-62 80s-78-24-80-60 44-76 78-74Z" />
                <path d="M300 286c12 0 24 9 26 22 2 15-8 31-25 33s-32-10-33-25 18-31 32-30Z" />
            </svg>

            <div class="relative px-5 pb-7 pt-6 sm:px-8 lg:p-0">
                <BrandMark tone="forest" />
            </div>

            <div class="relative hidden max-w-[460px] lg:block">
                <p class="text-hero font-semibold text-on-forest">
                    Turn a CSV into answers you can verify.
                </p>
                <ul class="mt-10 space-y-5">
                    <li v-for="item in CAPABILITIES" :key="item.title" class="flex gap-4">
                        <span aria-hidden="true"
                            class="grid h-9 w-9 shrink-0 place-items-center rounded-control border border-forest-line bg-forest-deep/40 text-gold">
                            <Icon :name="item.icon" :size="16" />
                        </span>
                        <span>
                            <span class="block text-body font-semibold text-on-forest">{{ item.title }}</span>
                            <span class="block text-data text-on-forest-muted">{{ item.text }}</span>
                        </span>
                    </li>
                </ul>
            </div>

            <p class="relative hidden items-center gap-2 text-caption text-on-forest-muted lg:flex">
                <Icon name="shield-check" :size="14" class="text-gold" />
                Sessions use a secure HTTP-only cookie. Passwords are never stored in the browser.
            </p>

        </aside>

        <!-- =====================================================
             FORM
        ====================================================== -->

        <main class="relative flex justify-center px-4 pb-12 sm:px-8 lg:items-center lg:py-12">

            <div
                class="-mt-3 w-full max-w-[420px] rounded-panel border border-line bg-surface p-6 shadow-raised sm:p-8 lg:mt-0 lg:border-transparent lg:bg-transparent lg:p-0 lg:shadow-none">

                <h1 class="text-display font-semibold text-ink">
                    {{ isRegister ? 'Create your account' : 'Welcome back' }}
                </h1>
                <p class="mt-1.5 text-body text-ink-muted">
                    {{ isRegister ? 'Register to start analyzing your datasets.' : 'Sign in to continue to your datasets.' }}
                </p>

                <!-- Mode switch -->

                <div class="mt-7 grid grid-cols-2 gap-1 rounded-control border border-line bg-sunken p-1" role="tablist"
                    aria-label="Sign in or create an account">
                    <button v-for="tab in [{ id: 'login', label: 'Sign in' }, { id: 'register', label: 'Create account' }]"
                        :key="tab.id" type="button" role="tab" :aria-selected="mode === tab.id"
                        :disabled="auth.pending" @click="switchMode(tab.id)" :class="mode === tab.id
                            ? 'bg-surface text-ink shadow-panel'
                            : 'text-ink-muted hover:text-ink'"
                        class="h-9 rounded-[6px] px-3 text-data font-medium transition-colors duration-150 disabled:opacity-70">
                        {{ tab.label }}
                    </button>
                </div>

                <!-- Messages -->

                <p v-if="auth.notice" role="status"
                    class="mt-5 flex items-start gap-2.5 rounded-control border border-success/20 bg-success-soft px-3.5 py-2.5 text-data text-success">
                    <Icon name="check" :size="16" class="mt-0.5" />
                    <span>{{ auth.notice }}</span>
                </p>

                <p v-if="auth.error" role="alert"
                    class="mt-5 flex items-start gap-2.5 rounded-control border border-danger/20 bg-danger-soft px-3.5 py-2.5 text-data text-danger">
                    <Icon name="error" :size="16" class="mt-0.5" />
                    <span>{{ auth.error }}</span>
                </p>

                <!-- Form -->

                <form class="mt-6 space-y-5" novalidate @submit.prevent="submit">

                    <div>
                        <label for="auth-email" class="mb-1.5 block text-data font-medium text-ink">
                            Email
                        </label>
                        <input id="auth-email" v-model="email" type="email" autocomplete="username" inputmode="email"
                            maxlength="254" :disabled="auth.pending" :aria-invalid="Boolean(emailError)"
                            :aria-describedby="emailError ? 'auth-email-error' : undefined" @blur="touched.email = true"
                            class="h-11 w-full rounded-control border bg-surface px-3.5 text-body text-ink shadow-[inset_0_1px_1px_rgb(24_61_48/0.04)] transition-[border-color,box-shadow] duration-150 placeholder:text-ink-subtle focus-visible:outline-none disabled:bg-sunken disabled:text-ink-muted"
                            :class="emailError
                                ? 'border-danger focus-visible:ring-[3px] focus-visible:ring-danger/15'
                                : 'border-line-strong hover:border-forest/40 focus-visible:border-forest focus-visible:ring-[3px] focus-visible:ring-forest/15'"
                            placeholder="you@company.com" />
                        <p v-if="emailError" id="auth-email-error"
                            class="mt-1.5 flex items-center gap-1.5 text-caption text-danger">
                            <Icon name="error" :size="14" />
                            {{ emailError }}
                        </p>
                    </div>

                    <div>
                        <label for="auth-password" class="mb-1.5 block text-data font-medium text-ink">
                            Password
                        </label>
                        <div class="relative">
                            <input id="auth-password" v-model="password" :type="showPassword ? 'text' : 'password'"
                                :autocomplete="isRegister ? 'new-password' : 'current-password'" maxlength="256"
                                :disabled="auth.pending" :aria-invalid="Boolean(passwordError)"
                                aria-describedby="auth-password-hint" @blur="touched.password = true"
                                class="h-11 w-full rounded-control border bg-surface pl-3.5 pr-11 text-body text-ink shadow-[inset_0_1px_1px_rgb(24_61_48/0.04)] transition-[border-color,box-shadow] duration-150 focus-visible:outline-none disabled:bg-sunken disabled:text-ink-muted"
                                :class="passwordError
                                    ? 'border-danger focus-visible:ring-[3px] focus-visible:ring-danger/15'
                                    : 'border-line-strong hover:border-forest/40 focus-visible:border-forest focus-visible:ring-[3px] focus-visible:ring-forest/15'" />
                            <button type="button" :disabled="auth.pending"
                                :aria-label="showPassword ? 'Hide password' : 'Show password'" :aria-pressed="showPassword"
                                class="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-control text-ink-muted transition-colors duration-150 hover:text-ink"
                                @click="showPassword = !showPassword">
                                <Icon :name="showPassword ? 'eye-off' : 'eye'" :size="16" />
                            </button>
                        </div>
                        <p id="auth-password-hint" class="mt-1.5 flex min-h-4 items-center gap-1.5 text-caption"
                            :class="passwordError ? 'text-danger' : 'text-ink-muted'">
                            <Icon v-if="passwordError" name="error" :size="14" />
                            {{ passwordError || (isRegister ? `At least ${MIN_PASSWORD_LENGTH} characters.` : '') }}
                        </p>
                    </div>

                    <Button type="submit" variant="primary" :loading="auth.pending" :disabled="!canSubmit"
                        class="h-11 w-full text-body">
                        {{ auth.pending
                            ? (isRegister ? 'Creating account…' : 'Signing in…')
                            : (isRegister ? 'Create account' : 'Sign in') }}
                    </Button>

                </form>

                <p class="mt-6 flex items-start gap-2 text-caption text-ink-muted lg:hidden">
                    <Icon name="shield-check" :size="14" class="mt-px text-forest" />
                    Sessions use a secure HTTP-only cookie. Passwords are never stored in the browser.
                </p>

            </div>

        </main>

    </div>
</template>
