// Follow-up context for /api/analyze: the canonical plan of the latest
// SUCCESSFUL analysis, echoed back so a follow-up ("break that down by
// region") can be applied to it. Only that one plan - no result rows,
// no transcript. Kept free of Vue so it can be tested with `node --test`.

function isScalar(value) {
    return ["string", "number", "boolean"].includes(typeof value);
}

// Context for the next request, built from a successful response for
// `datasetId`; null when the response cannot be a follow-up base.
export function buildFollowUpContext(response, datasetId) {
    const plan = response?.plan;

    if (!datasetId || !response?.success || !plan || !plan.metric || !plan.aggregation) {
        return null;
    }

    const filters = Array.isArray(plan.filters) ? plan.filters : [];

    // The backend only accepts scalar filter values; anything else
    // cannot round-trip, so no follow-up is offered for this result.
    if (!filters.every((filter) => isScalar(filter?.value))) {
        return null;
    }

    return {
        dataset_id: datasetId,
        previous_plan: {
            filters: filters.map(({ column, operator, value }) => ({
                column,
                operator,
                value,
            })),
            group_by: Array.isArray(plan.group_by) ? [...plan.group_by] : [],
            metric: plan.metric,
            aggregation: plan.aggregation,
            sort: plan.sort ?? "desc",
            sort_by: plan.sort_by ?? "metric",
            limit: plan.limit ?? null,
            visualization: plan.visualization ?? null,
            time_column: plan.time_column ?? null,
            time_granularity: plan.time_granularity ?? null,
        },
    };
}

// The context to attach to a request for `datasetId`, or null: only
// when the user wants a follow-up and the context is for that dataset.
export function selectFollowUpContext(context, datasetId, enabled) {
    if (!enabled || !context || !datasetId) {
        return null;
    }

    return context.dataset_id === datasetId ? context : null;
}
