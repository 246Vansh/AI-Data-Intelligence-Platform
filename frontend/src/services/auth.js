import { reactive, readonly } from "vue";

import {
    clearDatasetCache,
    fetchCurrentUser,
    getApiErrorMessage,
    loginRequest,
    logoutRequest,
    onAuthLost,
    registerRequest,
} from "./api.js";

// =========================================================
// AUTH STORE
// =========================================================
//
// One small app-wide reactive store (no Pinia - the project keeps
// shared state in plain service modules, like the dataset cache in
// api.js). It holds only the signed-in user's public profile and UI
// status. Passwords live only for the duration of a request; the
// session token is an HttpOnly cookie the browser manages - nothing
// here ever reads or writes browser storage or cookies (enforced by a
// source scan in auth.test.js).

export const AUTH_STATUS = {
    CHECKING: "checking",
    AUTHENTICATED: "authenticated",
    ANONYMOUS: "anonymous",
};

// Mirror of the backend rules (backend/auth/passwords.py, store.py) so
// obvious mistakes are caught before a request; the backend still
// enforces them.
export const MIN_PASSWORD_LENGTH = 12;
export const MAX_PASSWORD_LENGTH = 256;
const MAX_EMAIL_LENGTH = 254;

export function validateEmail(email) {
    const value = typeof email === "string" ? email.trim() : "";

    if (!value) {
        return "Enter your email address.";
    }
    if (value.length > MAX_EMAIL_LENGTH || /\s/.test(value)) {
        return "Enter a valid email address.";
    }

    const [local, domain, ...rest] = value.split("@");
    if (rest.length || !local || !domain) {
        return "Enter a valid email address.";
    }

    return "";
}

export function validatePassword(password) {
    if (typeof password !== "string" || !password) {
        return "Enter your password.";
    }
    if (password.length < MIN_PASSWORD_LENGTH || password.length > MAX_PASSWORD_LENGTH) {
        return `Password must be between ${MIN_PASSWORD_LENGTH} and ${MAX_PASSWORD_LENGTH} characters.`;
    }
    return "";
}

// User-facing text for an auth failure. Backend `detail` strings are
// fixed, safe messages; anything else (5xx pages, unexpected shapes)
// is replaced by a generic message, so no raw server output is shown.
export function authErrorMessage(error, fallback = "Something went wrong. Please try again.") {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail;

    if (status && status < 500 && typeof detail === "string") {
        return detail;
    }
    if (status === 503 && typeof detail === "string") {
        return detail;
    }
    if (!status && error?.request) {
        return getApiErrorMessage(error);
    }
    return fallback;
}

// Which top-level view App.vue may render. Protected content is only
// ever "dashboard" once the session has been positively confirmed.
export function resolveAppView(state) {
    if (state.status === AUTH_STATUS.AUTHENTICATED && state.user?.id) {
        return "dashboard";
    }
    if (state.status === AUTH_STATUS.CHECKING) {
        return "loading";
    }
    return "auth";
}

const DEFAULT_CLIENT = {
    fetchCurrentUser,
    login: loginRequest,
    register: registerRequest,
    logout: logoutRequest,
    clearSessionData: clearDatasetCache,
};

export function createAuthStore(client = DEFAULT_CLIENT) {
    const state = reactive({
        status: AUTH_STATUS.CHECKING,
        user: null,
        devMode: false,
        error: "",
        notice: "",
        pending: false,
    });

    // Single in-flight operation: a second submit while one is pending
    // returns the same promise instead of firing a duplicate request.
    let inFlight = null;

    function run(operation) {
        if (inFlight) {
            return inFlight;
        }

        state.pending = true;
        inFlight = (async () => {
            try {
                return await operation();
            } finally {
                state.pending = false;
                inFlight = null;
            }
        })();

        return inFlight;
    }

    function signIn(user, devMode = false) {
        // Start every session from an empty client cache.
        client.clearSessionData();
        state.user = { id: user.id, email: user.email ?? null, created_at: user.created_at ?? null };
        state.devMode = Boolean(devMode);
        state.status = AUTH_STATUS.AUTHENTICATED;
        state.error = "";
        state.notice = "";
    }

    function signOutLocally({ error = "", notice = "" } = {}) {
        client.clearSessionData();
        state.user = null;
        state.devMode = false;
        state.status = AUTH_STATUS.ANONYMOUS;
        state.error = error;
        state.notice = notice;
    }

    function restoreSession() {
        return run(async () => {
            state.status = AUTH_STATUS.CHECKING;

            try {
                const data = await client.fetchCurrentUser();
                if (!data?.user?.id) {
                    throw new Error("Malformed session response.");
                }
                signIn(data.user, data.dev_mode);
                return true;
            } catch (error) {
                signOutLocally({
                    error:
                        error?.response?.status === 401
                            ? ""
                            : authErrorMessage(error, "Unable to verify your session. Please sign in."),
                });
                return false;
            }
        });
    }

    function login(email, password) {
        return run(async () => {
            const problem = validateEmail(email) || (password ? "" : "Enter your password.");
            if (problem) {
                state.error = problem;
                return false;
            }

            state.error = "";
            state.notice = "";

            try {
                const user = await client.login(email.trim(), password);
                signIn(user);
                return true;
            } catch (error) {
                state.error = authErrorMessage(error, "Sign-in failed. Please try again.");
                return false;
            }
        });
    }

    function register(email, password) {
        return run(async () => {
            const problem = validateEmail(email) || validatePassword(password);
            if (problem) {
                state.error = problem;
                return false;
            }

            state.error = "";
            state.notice = "";

            try {
                await client.register(email.trim(), password);
            } catch (error) {
                state.error = authErrorMessage(error, "Registration failed. Please try again.");
                return false;
            }

            // Registration does not start a session; sign in with the
            // same credentials so the user lands in the dashboard.
            try {
                const user = await client.login(email.trim(), password);
                signIn(user);
                return true;
            } catch (error) {
                state.notice = "Account created. Please sign in.";
                state.error = "";
                return false;
            }
        });
    }

    function logout() {
        return run(async () => {
            try {
                await client.logout();
            } catch {
                // The backend clears the cookie even when it reports a
                // failure; locally we always end the session.
            }
            signOutLocally();
            return true;
        });
    }

    // Called on a 401 from any non-auth endpoint. Idempotent and makes
    // no requests, so concurrent 401s cannot cascade or loop.
    function handleAuthLost() {
        if (state.status !== AUTH_STATUS.AUTHENTICATED) {
            return;
        }
        signOutLocally({ error: "Your session has ended. Please sign in again." });
    }

    function clearMessages() {
        state.error = "";
        state.notice = "";
    }

    return {
        state: readonly(state),
        restoreSession,
        login,
        register,
        logout,
        handleAuthLost,
        clearMessages,
    };
}

export const authStore = createAuthStore();

onAuthLost(() => authStore.handleAuthLost());
