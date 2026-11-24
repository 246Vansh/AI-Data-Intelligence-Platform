import assert from "node:assert/strict";
import { test } from "node:test";

import { columnKind, describeColumns, isEmptyString, isMissing, kindSummary, missingPercentage } from "./columnInsight.js";

test("columnKind follows the backend data_type vocabulary", () => {
    assert.equal(columnKind("integer"), "number");
    assert.equal(columnKind("float"), "number");
    assert.equal(columnKind("numeric"), "number");
    assert.equal(columnKind("datetime"), "date");
    assert.equal(columnKind("boolean"), "boolean");
    assert.equal(columnKind("string"), "text");
    assert.equal(columnKind("geometry"), "other");
});

test("columnKind: a string column with the backend's time role reads as a date; a numeric one stays numeric", () => {
    assert.equal(columnKind("string", "time"), "date");
    assert.equal(columnKind("integer", "time"), "number");
});

test("columnKind without a type falls back to preview values, never guessing dates", () => {
    assert.equal(columnKind(null, null, [1, 2.5, null]), "number");
    assert.equal(columnKind(null, null, [true, false]), "boolean");
    assert.equal(columnKind(null, null, ["2024-01-01"]), "text");
    assert.equal(columnKind(null, null, [null, undefined]), "other");
});

test("missing vs empty values are distinguished", () => {
    assert.ok(isMissing(null) && isMissing(undefined));
    assert.ok(!isMissing("") && !isMissing(0) && !isMissing(false));
    assert.ok(isEmptyString("") && isEmptyString("  "));
    assert.ok(!isEmptyString("a") && !isEmptyString(null));
});

test("describeColumns copies backend figures and leaves absent ones null", () => {
    const described = describeColumns({
        columns: ["revenue", "region", "note"],
        rows: [
            { revenue: 10, region: "North", note: null },
            { revenue: null, region: "", note: "x" },
        ],
        profile: {
            rows: 2000,
            column_details: {
                revenue: { data_type: "float", missing_count: 3, missing_percentage: 0.15, unique_values: 1990 },
                region: { data_type: "string", missing_count: 0, missing_percentage: 0, unique_values: 4 },
            },
        },
        metadata: {
            columns: {
                revenue: { role: "metric", sample_values: [10, 12] },
                region: { role: "dimension", sample_values: ["North"] },
            },
        },
    });

    assert.deepEqual(described[0], {
        name: "revenue", kind: "number", dataType: "float", role: "metric", totalRows: 2000,
        missingCount: 3, missingPercentage: 0.15, uniqueValues: 1990, sampleValues: [10, 12],
        previewMissing: 1, previewEmpty: 0,
    });
    assert.equal(described[1].previewEmpty, 1);
    assert.equal(described[1].missingCount, 0); // a real zero, not "unknown"
    // No profile/metadata entry: nothing is invented.
    assert.equal(described[2].dataType, null);
    assert.equal(described[2].missingCount, null);
    assert.equal(described[2].uniqueValues, null);
    assert.equal(described[2].kind, "text");
});

test("describeColumns works with no profile or metadata at all", () => {
    const [column] = describeColumns({ columns: ["a"], rows: [{ a: 1 }] });
    assert.equal(column.kind, "number");
    assert.equal(column.totalRows, null);
    assert.deepEqual(column.sampleValues, []);
});

test("kindSummary counts columns per kind in a fixed order", () => {
    const summary = kindSummary([{ kind: "text" }, { kind: "number" }, { kind: "number" }]);
    assert.deepEqual(summary.map((entry) => [entry.kind, entry.count]), [["number", 2], ["text", 1]]);
});

// ---------------------------------------------------------
// /metadata instead of /profile (the Data workspace no longer requests
// /profile). Both responses come from the same backend per-column scan;
// these are the shapes data_engine returns for the same dataset.
// ---------------------------------------------------------

const SAME_DATASET = {
    profile: {
        rows: 2000,
        column_details: {
            revenue: { data_type: "float", missing_count: 3, missing_percentage: 0.15, unique_values: 1990 },
            region: { data_type: "string", missing_count: 0, missing_percentage: 0, unique_values: 4 },
            note: { data_type: "string", missing_count: 1999, missing_percentage: 99.95, unique_values: 1 },
            ratio: { data_type: "float", missing_count: 1, missing_percentage: 0.05, unique_values: 1999 },
        },
    },
    metadata: {
        row_count: 2000,
        columns: {
            revenue: { data_type: "float", role: "metric", missing_count: 3, unique_values: 1990, sample_values: [10, 12] },
            region: { data_type: "string", role: "dimension", missing_count: 0, unique_values: 4, sample_values: ["North"] },
            note: { data_type: "string", role: "dimension", missing_count: 1999, unique_values: 1, sample_values: ["x"] },
            ratio: { data_type: "float", role: "metric", missing_count: 1, unique_values: 1999, sample_values: [0.5] },
        },
    },
};

test("metadata alone gives the same column details the profile gave, missing percentages included", () => {
    const columns = ["revenue", "region", "note", "ratio"];
    const rows = [{ revenue: 10, region: "North", note: null, ratio: 0.5 }];

    const withProfile = describeColumns({ columns, rows, ...SAME_DATASET });
    const metadataOnly = describeColumns({ columns, rows, metadata: SAME_DATASET.metadata });

    assert.deepEqual(metadataOnly, withProfile);
    assert.deepEqual(metadataOnly.map((column) => column.missingPercentage), [0.15, 0, 99.95, 0.05]);
    assert.ok(metadataOnly.every((column) => column.totalRows === 2000));
});

test("missingPercentage follows the backend formula: round(count / rows * 100, 2), 0 for no rows", () => {
    assert.equal(missingPercentage(3, 2000), 0.15);
    assert.equal(missingPercentage(1, 3), 33.33);
    assert.equal(missingPercentage(2, 3), 66.67);
    assert.equal(missingPercentage(0, 10), 0);
    assert.equal(missingPercentage(5, 0), 0);
    assert.equal(missingPercentage(null, 10), null);
    assert.equal(missingPercentage(1, null), null);
});
