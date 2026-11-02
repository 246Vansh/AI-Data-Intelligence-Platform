// Run with: node --test src/services/auth.test.js
// Built-in node:test - no test framework dependency.
import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// ---------------------------------------------------------
// Browser-storage spies, installed BEFORE the modules load so even an
// import-time write would be caught.
// ---------------------------------------------------------

const storageWrites = [];

function spyStorage(name) {
    return {
        getItem: () => null,
        setItem: (key, value) => storageWrites.push({ name, key, value }),
        removeItem: () => {},
        clear: () => {},
        key: () => null,
        length: 0,
    };
}

globalThis.localStorage = spyStorage("localStorage");
globalThis.sessionStorage = spyStorage("sessionStorage");

const { AxiosError } = await import("axios");
const apiModule = await import("./api.js");
const {
    AUTH_STATUS,
    authErrorMessage,
    authStore,
    createAuthStore,
    resolveAppView,
    validateEmail,
    validatePassword,
} = await import("./auth.js");

// A fake `document` would break Vue's DOM runtime at import, so the
// cookie spy goes in after loading; import-time cookie access is
// covered by the source scan at the end of this file.
const cookieWrites = [];
globalThis.document = {
    get cookie() {
        return "";
    },
    set cookie(value) {
        cookieWrites.push(value);
    },
};

const ALICE = { id: "11111111-1111-1111-1111-111111111111", email: "alice@example.com", created_at: "2026-11-02T00:00:00+00:00" };
const PASSWORD = "alice password 123";

function httpError(status, data) {
    const config = { url: "/x" };
    return new AxiosError("Request failed", "ERR_BAD_RESPONSE", config, {}, { status, data, headers: {}, config });
}

function networkError() {
    return new AxiosError("Network Error", "ERR_NETWORK", { url: "/x" }, {});
}

function fakeClient(overrides = {}) {
    const calls = { fetchCurrentUser: 0, login: [], register: [], logout: 0, clearSessionData: 0 };
    const client = {
        fetchCurrentUser: async () => {
            calls.fetchCurrentUser += 1;
            return { user: ALICE, dev_mode: false };
        },
        login: async (email, password) => {
            calls.login.push({ email, password });
            return ALICE;
        },
        register: async (email, password) => {
            calls.register.push({ email, password });
            return ALICE;
        },
        logout: async () => {
            calls.logout += 1;
            return { status: "logged_out" };
        },
        clearSessionData: () => {
            calls.clearSessionData += 1;
        },
        ...overrides,
    };
    return { client, calls };
}

function deferred() {
    let resolve;
    let reject;
    const promise = new Promise((res, rej) => {
        resolve = res;
        reject = rej;
    });
    return { promise, resolve, reject };
}

// =========================================================
// SESSION RESTORATION + VIEW GATING
// =========================================================

test("starts in CHECKING and renders the loading view, never the dashboard", () => {
    const { client } = fakeClient();
    const store = createAuthStore(client);

    assert.equal(store.state.status, AUTH_STATUS.CHECKING);
    assert.equal(resolveAppView(store.state), "loading");
});

test("no dashboard while the session check is still pending", async () => {
    const pending = deferred();
    const { client } = fakeClient({ fetchCurrentUser: () => pending.promise });
    const store = createAuthStore(client);

    const restoring = store.restoreSession();
    assert.equal(resolveAppView(store.state), "loading");
    assert.equal(store.state.user, null);

    pending.resolve({ user: ALICE, dev_mode: false });
    await restoring;

    assert.equal(resolveAppView(store.state), "dashboard");
});

test("restoreSession success signs in with a clean cache", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);

    assert.equal(await store.restoreSession(), true);

    assert.equal(store.state.status, AUTH_STATUS.AUTHENTICATED);
    assert.deepEqual(store.state.user, ALICE);
    assert.equal(store.state.error, "");
    assert.equal(calls.clearSessionData, 1);
});

test("restoreSession 401 shows the sign-in screen without an error", async () => {
    const { client } = fakeClient({
        fetchCurrentUser: async () => {
            throw httpError(401, { detail: "Not authenticated." });
        },
    });
    const store = createAuthStore(client);

    assert.equal(await store.restoreSession(), false);

    assert.equal(store.state.status, AUTH_STATUS.ANONYMOUS);
    assert.equal(store.state.user, null);
    assert.equal(store.state.error, "");
    assert.equal(resolveAppView(store.state), "auth");
});

test("restoreSession server/network failure fails closed with a safe message", async () => {
    for (const error of [httpError(500, "<html>Traceback (most recent call last)…</html>"), networkError()]) {
        const { client } = fakeClient({
            fetchCurrentUser: async () => {
                throw error;
            },
        });
        const store = createAuthStore(client);

        await store.restoreSession();

        assert.equal(resolveAppView(store.state), "auth");
        assert.ok(store.state.error);
        assert.doesNotMatch(store.state.error, /Traceback|<html>/);
    }
});

test("a malformed /me response never reaches the dashboard", async () => {
    const { client } = fakeClient({ fetchCurrentUser: async () => ({ user: null }) });
    const store = createAuthStore(client);

    await store.restoreSession();

    assert.equal(resolveAppView(store.state), "auth");
});

test("resolveAppView requires an authenticated status AND a user id", () => {
    assert.equal(resolveAppView({ status: "authenticated", user: null }), "auth");
    assert.equal(resolveAppView({ status: "authenticated", user: {} }), "auth");
    assert.equal(resolveAppView({ status: "anonymous", user: ALICE }), "auth");
    assert.equal(resolveAppView({ status: "checking", user: ALICE }), "loading");
});

// =========================================================
// LOGIN
// =========================================================

test("login success", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);
    await store.restoreSession();
    await store.logout();

    assert.equal(await store.login("  alice@example.com ", PASSWORD), true);

    assert.deepEqual(calls.login, [{ email: "alice@example.com", password: PASSWORD }]);
    assert.equal(store.state.status, AUTH_STATUS.AUTHENTICATED);
    assert.equal(store.state.user.id, ALICE.id);
    assert.equal(JSON.stringify(store.state).includes(PASSWORD), false);
});

test("login failure shows the backend's safe message", async () => {
    const cases = [
        [httpError(401, { detail: "Invalid email or password." }), "Invalid email or password."],
        [httpError(429, { detail: "Too many failed login attempts. Try again later." }), "Too many failed login attempts. Try again later."],
        [httpError(503, { detail: "Authentication is busy. Please retry shortly." }), "Authentication is busy. Please retry shortly."],
        [httpError(500, "Internal Server Error\nTraceback ..."), "Sign-in failed. Please try again."],
        [httpError(502, { detail: { trace: "secret internals" } }), "Sign-in failed. Please try again."],
    ];

    for (const [error, expected] of cases) {
        const { client } = fakeClient({
            login: async () => {
                throw error;
            },
        });
        const store = createAuthStore(client);

        assert.equal(await store.login(ALICE.email, PASSWORD), false);
        assert.equal(store.state.error, expected);
        assert.notEqual(store.state.status, AUTH_STATUS.AUTHENTICATED);
    }
});

test("login validates the email before sending a request", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);

    assert.equal(await store.login("not-an-email", PASSWORD), false);
    assert.equal(await store.login(ALICE.email, ""), false);

    assert.equal(calls.login.length, 0);
    assert.ok(store.state.error);
});

test("concurrent submits send only one request", async () => {
    const gate = deferred();
    let requests = 0;
    const { client } = fakeClient({
        login: async () => {
            requests += 1;
            await gate.promise;
            return ALICE;
        },
    });
    const store = createAuthStore(client);

    const first = store.login(ALICE.email, PASSWORD);
    const second = store.login(ALICE.email, PASSWORD);
    assert.equal(store.state.pending, true);

    gate.resolve();
    assert.deepEqual(await Promise.all([first, second]), [true, true]);

    assert.equal(requests, 1);
    assert.equal(store.state.pending, false);
});

// =========================================================
// REGISTER
// =========================================================

test("register success signs the new user in", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);

    assert.equal(await store.register("new@example.com", PASSWORD), true);

    assert.equal(calls.register.length, 1);
    assert.equal(calls.login.length, 1);
    assert.equal(store.state.status, AUTH_STATUS.AUTHENTICATED);
});

test("register failure shows the backend message and does not sign in", async () => {
    for (const [status, detail] of [
        [409, "An account with this email already exists."],
        [403, "Registration is disabled."],
        [400, "Password must be between 12 and 256 characters."],
    ]) {
        const { client, calls } = fakeClient({
            register: async () => {
                throw httpError(status, { detail });
            },
        });
        const store = createAuthStore(client);

        assert.equal(await store.register("new@example.com", PASSWORD), false);
        assert.equal(store.state.error, detail);
        assert.equal(calls.login.length, 0);
    }
});

test("register validates password length before sending", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);

    assert.equal(await store.register("new@example.com", "short"), false);
    assert.equal(await store.register("new@example.com", "x".repeat(257)), false);

    assert.equal(calls.register.length, 0);
    assert.match(store.state.error, /between 12 and 256/);
});

test("register succeeds but auto sign-in fails -> notice, not error", async () => {
    const { client } = fakeClient({
        login: async () => {
            throw httpError(503, { detail: "Authentication is busy. Please retry shortly." });
        },
    });
    const store = createAuthStore(client);

    assert.equal(await store.register("new@example.com", PASSWORD), false);
    assert.equal(store.state.notice, "Account created. Please sign in.");
    assert.equal(store.state.error, "");
    assert.equal(store.state.status, AUTH_STATUS.CHECKING);
});

// =========================================================
// LOGOUT + AUTH LOSS
// =========================================================

test("logout clears session data and returns to the sign-in screen", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);
    await store.restoreSession();
    const clearsBefore = calls.clearSessionData;

    await store.logout();

    assert.equal(calls.logout, 1);
    assert.equal(calls.clearSessionData, clearsBefore + 1);
    assert.equal(store.state.user, null);
    assert.equal(resolveAppView(store.state), "auth");
});

test("logout still ends the local session when the request fails", async () => {
    const { client, calls } = fakeClient({
        logout: async () => {
            throw httpError(503, { detail: "Authentication is temporarily unavailable." });
        },
    });
    const store = createAuthStore(client);
    await store.restoreSession();

    await store.logout();

    assert.equal(store.state.status, AUTH_STATUS.ANONYMOUS);
    assert.equal(store.state.user, null);
    assert.ok(calls.clearSessionData >= 2);
});

test("handleAuthLost signs out once and makes no requests", async () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);
    await store.restoreSession();
    const before = { ...calls, login: calls.login.length };

    store.handleAuthLost();
    store.handleAuthLost();

    assert.equal(store.state.status, AUTH_STATUS.ANONYMOUS);
    assert.match(store.state.error, /session has ended/);
    assert.equal(calls.clearSessionData, before.clearSessionData + 1);
    assert.equal(calls.fetchCurrentUser, before.fetchCurrentUser);
    assert.equal(calls.logout, 0);
});

test("handleAuthLost is a no-op when not signed in", () => {
    const { client, calls } = fakeClient();
    const store = createAuthStore(client);

    store.handleAuthLost();

    assert.equal(store.state.status, AUTH_STATUS.CHECKING);
    assert.equal(calls.clearSessionData, 0);
});

// =========================================================
// CENTRAL 401 HANDLING (real api.js axios instance)
// =========================================================

function withAdapter(handler, fn) {
    const original = apiModule.api.defaults.adapter;
    apiModule.api.defaults.adapter = handler;
    return fn().finally(() => {
        apiModule.api.defaults.adapter = original;
    });
}

function respond(config, status, data) {
    const response = { status, statusText: String(status), data, headers: {}, config };
    if (status >= 200 && status < 300) {
        return Promise.resolve(response);
    }
    return Promise.reject(new AxiosError("Request failed", "ERR_BAD_REQUEST", config, {}, response));
}

test("401 from a data endpoint clears the dataset cache and notifies once, without retrying", async () => {
    const hits = [];
    let lost = 0;
    const stop = apiModule.onAuthLost(() => {
        lost += 1;
    });

    await withAdapter(
        (config) => {
            hits.push(config.url);
            if (config.url === "/dataset") {
                return respond(config, 401, { detail: "Not authenticated." });
            }
            return respond(config, 200, { ok: true });
        },
        async () => {
            await apiModule.getDatasetProfile("ds-1");
            await apiModule.getDatasetProfile("ds-1"); // served from cache
            assert.equal(hits.filter((u) => u === "/dataset/ds-1/profile").length, 1);

            await assert.rejects(apiModule.listDatasets(), (error) => error.response.status === 401);

            assert.equal(lost, 1);
            assert.equal(hits.filter((u) => u === "/dataset").length, 1); // no retry

            await apiModule.getDatasetProfile("ds-1"); // cache was cleared
            assert.equal(hits.filter((u) => u === "/dataset/ds-1/profile").length, 2);
        },
    );

    stop();
});

test("401 from /auth/* endpoints does not trigger auth-loss handling", async () => {
    let lost = 0;
    const stop = apiModule.onAuthLost(() => {
        lost += 1;
    });

    await withAdapter(
        (config) => respond(config, 401, { detail: "Invalid email or password." }),
        async () => {
            await assert.rejects(apiModule.fetchCurrentUser());
            await assert.rejects(apiModule.loginRequest(ALICE.email, PASSWORD));
        },
    );

    assert.equal(lost, 0);
    stop();
});

test("non-401 errors do not trigger auth-loss handling", async () => {
    let lost = 0;
    const stop = apiModule.onAuthLost(() => {
        lost += 1;
    });

    await withAdapter(
        (config) => respond(config, 404, { detail: "No dataset found" }),
        async () => {
            await assert.rejects(apiModule.listDatasets());
        },
    );

    assert.equal(lost, 0);
    stop();
});

test("the app-wide store signs out when a data request returns 401", async () => {
    await withAdapter(
        (config) => {
            if (config.url === "/auth/me") {
                return respond(config, 200, { user: ALICE, dev_mode: false });
            }
            return respond(config, 401, { detail: "Not authenticated." });
        },
        async () => {
            await authStore.restoreSession();
            assert.equal(authStore.state.status, AUTH_STATUS.AUTHENTICATED);

            await assert.rejects(apiModule.listDatasets());
        },
    );

    assert.equal(authStore.state.status, AUTH_STATUS.ANONYMOUS);
    assert.equal(authStore.state.user, null);
    assert.equal(resolveAppView(authStore.state), "auth");
});

test("axios sends credentials (cookie) with requests", () => {
    assert.equal(apiModule.api.defaults.withCredentials, true);
});

// =========================================================
// VALIDATION + ERROR TEXT
// =========================================================

test("validation mirrors backend rules", () => {
    assert.equal(validateEmail("a@b.co"), "");
    assert.ok(validateEmail(""));
    assert.ok(validateEmail("no-at"));
    assert.ok(validateEmail("a@b@c"));
    assert.ok(validateEmail("a b@c.d"));
    assert.equal(validatePassword("x".repeat(12)), "");
    assert.equal(validatePassword("x".repeat(256)), "");
    assert.ok(validatePassword("x".repeat(11)));
    assert.ok(validatePassword("x".repeat(257)));
});

test("authErrorMessage never surfaces raw server output", () => {
    assert.equal(authErrorMessage(httpError(500, "Traceback (most recent call last)")), "Something went wrong. Please try again.");
    assert.equal(authErrorMessage(httpError(400, { detail: [{ msg: "x", input: "pw" }] })), "Something went wrong. Please try again.");
    assert.equal(authErrorMessage(networkError()), "Unable to connect to the analysis server.");
});

// =========================================================
// NO CREDENTIAL STORAGE
// =========================================================

test("no flow writes to localStorage, sessionStorage or document.cookie", async () => {
    const { client } = fakeClient();
    const store = createAuthStore(client);

    await store.restoreSession();
    await store.logout();
    await store.login(ALICE.email, PASSWORD);
    await store.register("new@example.com", PASSWORD);
    store.handleAuthLost();

    assert.deepEqual(storageWrites, []);
    assert.deepEqual(cookieWrites, []);
});

test("frontend source never references browser storage or document.cookie", () => {
    const srcDir = fileURLToPath(new URL("..", import.meta.url));
    const offenders = [];

    function walk(dir) {
        for (const name of readdirSync(dir)) {
            const path = join(dir, name);
            if (statSync(path).isDirectory()) {
                walk(path);
            } else if (/\.(js|vue)$/.test(name) && !name.endsWith(".test.js")) {
                const text = readFileSync(path, "utf8");
                if (/localStorage|sessionStorage|document\.cookie/.test(text)) {
                    offenders.push(path);
                }
            }
        }
    }

    walk(srcDir);
    assert.deepEqual(offenders, []);
});
