// Run with: node --test src/services/followUpContext.test.js
// Built-in node:test - no test framework dependency.
import test from "node:test";
import assert from "node:assert/strict";

import { buildFollowUpContext, selectFollowUpContext } from "./followUpContext.js";

const DATASET_A = "aaaaaaaa-0000-0000-0000-000000000000";
const DATASET_B = "bbbbbbbb-0000-0000-0000-000000000000";

function response(planOverrides = {}, extra = {}) {
    return {
        success: true,
        data: { columns: ["product", "sum_amount"], rows: [{ product: "x", sum_amount: 1 }] },
        plan: {
            filters: [{ column: "region", operator: "=", value: "North" }],
            group_by: ["product"],
            metric: "amount",
            aggregation: "sum",
            sort: "desc",
            sort_by: "metric",
            limit: 5,
            visualization: "bar",
            time_column: null,
            time_granularity: null,
            ...planOverrides,
        },
        ...extra,
    };
}

test("builds a bounded context from the canonical plan only", () => {
    const context = buildFollowUpContext(response(), DATASET_A);

    assert.deepEqual(context, {
        dataset_id: DATASET_A,
        previous_plan: {
            filters: [{ column: "region", operator: "=", value: "North" }],
            group_by: ["product"],
            metric: "amount",
            aggregation: "sum",
            sort: "desc",
            sort_by: "metric",
            limit: 5,
            visualization: "bar",
            time_column: null,
            time_granularity: null,
        },
    });
    // No result rows or other response fields leak into the context.
    assert.equal(JSON.stringify(context).includes("sum_amount"), false);
});

test("a failed or unusable response produces no context", () => {
    assert.equal(buildFollowUpContext({ success: false, plan: response().plan }, DATASET_A), null);
    assert.equal(buildFollowUpContext(response({ metric: null }), DATASET_A), null);
    assert.equal(buildFollowUpContext({ success: true }, DATASET_A), null);
    assert.equal(buildFollowUpContext(response(), null), null);
    assert.equal(
        buildFollowUpContext(
            response({ filters: [{ column: "c", operator: "=", value: { nested: 1 } }] }),
            DATASET_A,
        ),
        null,
    );
});

test("context is attached only for the same dataset and when enabled", () => {
    const context = buildFollowUpContext(response(), DATASET_A);

    assert.equal(selectFollowUpContext(context, DATASET_A, true), context);
    assert.equal(selectFollowUpContext(context, DATASET_B, true), null);
    assert.equal(selectFollowUpContext(context, DATASET_A, false), null);
    assert.equal(selectFollowUpContext(null, DATASET_A, true), null);
    assert.equal(selectFollowUpContext(context, null, true), null);
});

test("the latest successful response replaces the previous context", () => {
    const first = buildFollowUpContext(response(), DATASET_A);
    const second = buildFollowUpContext(
        response({ group_by: ["product", "region"], limit: null }),
        DATASET_A,
    );

    assert.notDeepEqual(first, second);
    assert.deepEqual(second.previous_plan.group_by, ["product", "region"]);
    assert.equal(second.previous_plan.limit, null);
});
