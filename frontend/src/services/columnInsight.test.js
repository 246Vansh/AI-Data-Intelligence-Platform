import assert from "node:assert/strict";
import { test } from "node:test";

import { columnKind, describeColumns, isEmptyString, isMissing, kindSummary } from "./columnInsight.js";

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
