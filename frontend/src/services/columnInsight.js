// =========================================================
// COLUMN INSIGHT (Data workspace)
// =========================================================
//
// Pure helpers that merge what the app ALREADY has for a dataset - the
// preview payload, the cached /profile response and the cached
// /metadata response - into one per-column description for the Data
// workspace's column inspector. Nothing here computes a new statistic:
// every figure is copied from a backend response, or left null when
// that response is missing or does not carry it.
//
// Backend vocabulary (data_engine): profile/metadata `data_type` is
// one of "integer" | "float" | "numeric" | "datetime" | "boolean" |
// "string"; metadata `role` is "metric" | "dimension" | "time".

export const COLUMN_KINDS = Object.freeze({
    number: { label: "Number", icon: "type-number" },
    date: { label: "Date / time", icon: "type-date" },
    boolean: { label: "Boolean", icon: "type-boolean" },
    text: { label: "Text", icon: "type-text" },
    other: { label: "Other", icon: "type-other" },
});

const NUMBER_TYPES = new Set(["integer", "float", "numeric"]);

// Display kind of a column. The backend's data_type decides; a text
// column the backend itself classifies as a "time" role (e.g. ISO date
// strings in a CSV) is shown as a date. Without any type information
// the preview values decide (number / boolean only - strings are not
// guessed to be dates).
export function columnKind(dataType, role, previewValues = []) {
    const type = String(dataType ?? "").toLowerCase();

    if (NUMBER_TYPES.has(type)) return "number";
    if (type === "datetime") return "date";
    if (type === "boolean") return "boolean";
    if (type === "string") return role === "time" ? "date" : "text";
    if (type) return "other";

    const present = previewValues.filter((value) => !isMissing(value));
    if (present.length && present.every((value) => typeof value === "number")) return "number";
    if (present.length && present.every((value) => typeof value === "boolean")) return "boolean";
    return present.length ? "text" : "other";
}

// Missing in the preview: JSON null (the backend sanitizes NaN/NaT to
// null) or absent. An empty string is a value, but an empty one - the
// table marks the two differently.
export function isMissing(value) {
    return value === null || value === undefined;
}

export function isEmptyString(value) {
    return typeof value === "string" && value.trim() === "";
}

function finiteOrNull(value) {
    const number = Number(value);
    return value !== null && value !== undefined && value !== "" && Number.isFinite(number) ? number : null;
}

// One entry per preview column, in preview order.
export function describeColumns({ columns = [], rows = [], profile = null, metadata = null } = {}) {
    const details = profile?.column_details || {};
    const meta = metadata?.columns || {};
    const totalRows = finiteOrNull(profile?.rows);

    return columns.map((name) => {
        const detail = details[name] || {};
        const info = meta[name] || {};
        const dataType = detail.data_type ?? info.data_type ?? null;
        const role = info.role ?? null;
        const previewValues = rows.map((row) => row?.[name]);

        return {
            name,
            kind: columnKind(dataType, role, previewValues),
            dataType,
            role,
            totalRows,
            missingCount: finiteOrNull(detail.missing_count ?? profile?.missing_values?.[name] ?? info.missing_count),
            missingPercentage: finiteOrNull(detail.missing_percentage),
            uniqueValues: finiteOrNull(detail.unique_values ?? info.unique_values),
            sampleValues: Array.isArray(info.sample_values) ? info.sample_values : [],
            previewMissing: previewValues.filter(isMissing).length,
            previewEmpty: previewValues.filter(isEmptyString).length,
        };
    });
}

// How many columns of each kind, in COLUMN_KINDS order, zero counts
// dropped. A count of existing columns, not a statistic about values.
export function kindSummary(described) {
    return Object.keys(COLUMN_KINDS)
        .map((kind) => ({ kind, ...COLUMN_KINDS[kind], count: described.filter((column) => column.kind === kind).length }))
        .filter((entry) => entry.count > 0);
}
