// Run with: node --test src/services/userDisplay.test.js
import test from "node:test";
import assert from "node:assert/strict";

import { displayName, initials } from "./userDisplay.js";

test("name and initials come from the email's local part", () => {
    assert.equal(displayName({ email: "jane.doe@example.com" }), "Jane Doe");
    assert.equal(initials({ email: "jane.doe@example.com" }), "JD");
    assert.equal(displayName({ email: "alex@example.com" }), "Alex");
    assert.equal(initials({ email: "alex@example.com" }), "AL");
});

test("numeric-only parts are not used as a name", () => {
    assert.equal(displayName({ email: "tester1-20240101@example.com" }), "Tester1");
    assert.equal(displayName({ email: "12345@example.com" }), "12345@example.com");
});

test("missing user falls back safely", () => {
    assert.equal(displayName(null), "Account");
    assert.equal(initials(null), "?");
});
