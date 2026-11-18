// =========================================================
// USER DISPLAY (name + initials from the account email)
// =========================================================
//
// Accounts only have an email (backend/auth), so the shell derives a
// readable name from its local part: "jane.doe@x" -> "Jane Doe",
// "harsh@x" -> "Harsh". Purely presentational; nothing is stored.

function localParts(email) {
    const local = String(email || "").split("@")[0];
    return local.split(/[._\-+]+/).filter(Boolean);
}

export function displayName(user) {
    const parts = localParts(user?.email).filter((part) => /[a-z]/i.test(part));
    if (!parts.length) {
        return user?.email || "Account";
    }
    return parts
        .slice(0, 2)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1).toLowerCase())
        .join(" ");
}

export function initials(user) {
    const parts = localParts(user?.email);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    const local = parts[0] || "";
    return (local.slice(0, 2) || "?").toUpperCase();
}
