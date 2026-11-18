<script setup>
import { computed } from "vue";

import { COLUMN_KINDS } from "../../services/columnInsight";
import Icon from "../ui/Icon.vue";

// =========================================================
// COLUMN DETAILS
// =========================================================
//
// One column, described only with what the backend already returned
// (see services/columnInsight.js): type and role from /profile and
// /metadata, missing and unique counts from the cached profile, sample
// values from the cached metadata. A figure the responses do not carry
// is left out - never estimated. Used in the Data workspace's docked
// inspector and in the mobile bottom sheet.

const props = defineProps({
    column: { type: Object, required: true },
    // Hide the name heading when the container already shows it
    // (the mobile sheet's title).
    showName: { type: Boolean, default: true },
});

const kind = computed(() => COLUMN_KINDS[props.column.kind] || COLUMN_KINDS.other);

const ROLE_LABELS = { metric: "Measure", dimension: "Dimension", time: "Time" };
const roleLabel = computed(() => ROLE_LABELS[props.column.role] || props.column.role || null);

const formatCount = (value) => Number(value).toLocaleString("en-US");

// Backend missing_percentage is already a percentage (0-100).
const missingPercent = computed(() => {
    const value = props.column.missingPercentage;
    if (value === null) return null;
    return value > 0 && value < 0.1 ? "<0.1%" : `${Number(value.toFixed(1))}%`;
});

// Identifier-style names (snake_case) wrap after an underscore, not
// mid-word.
const nameParts = computed(() => props.column.name.split(/(?<=_)/));

const hasStatistics = computed(() => props.column.missingCount !== null || props.column.uniqueValues !== null);

function formatSample(value) {
    if (value === null || value === undefined) return "null";
    if (typeof value === "string" && value.trim() === "") return "empty";
    return String(value);
}
</script>

<template>
    <div class="space-y-4">

        <header v-if="showName" class="space-y-1">
            <h4 class="font-mono text-data font-semibold text-ink [overflow-wrap:anywhere]"><template
                    v-for="(part, index) in nameParts" :key="index">{{ part }}<wbr /></template></h4>
            <p class="flex items-center gap-1.5 text-caption text-ink-muted">
                <Icon :name="kind.icon" :size="14" class="text-forest" />
                {{ kind.label }}
                <span v-if="column.dataType" class="font-mono">· {{ column.dataType }}</span>
            </p>
        </header>

        <dl class="divide-y divide-line border-y border-line text-data">

            <div v-if="!showName" class="flex items-baseline justify-between gap-4 py-2.5">
                <dt class="text-ink-muted">Type</dt>
                <dd class="flex items-center gap-1.5 text-ink">
                    <Icon :name="kind.icon" :size="14" class="text-forest" />
                    {{ kind.label }}
                    <span v-if="column.dataType" class="font-mono text-caption text-ink-muted">{{ column.dataType }}</span>
                </dd>
            </div>

            <div v-if="roleLabel" class="flex items-baseline justify-between gap-4 py-2.5">
                <dt class="text-ink-muted">Role in analysis</dt>
                <dd class="text-ink">{{ roleLabel }}</dd>
            </div>

            <div v-if="column.missingCount !== null" class="py-2.5">
                <div class="flex items-baseline justify-between gap-4">
                    <dt class="text-ink-muted">Missing values</dt>
                    <dd class="tabular-nums text-ink">
                        <template v-if="column.missingCount > 0">
                            <span class="font-semibold">{{ formatCount(column.missingCount) }}</span>
                            <span v-if="missingPercent" class="text-ink-muted"> · {{ missingPercent }}</span>
                        </template>
                        <span v-else>None</span>
                    </dd>
                </div>
                <div v-if="column.missingCount > 0 && column.missingPercentage !== null" class="mt-2 h-1 overflow-hidden rounded-full bg-sunken"
                    role="img" :aria-label="`${missingPercent} of rows missing`">
                    <div class="h-full rounded-full bg-gold"
                        :style="{ width: `${Math.max(column.missingPercentage, 1.5)}%` }">
                    </div>
                </div>
                <p v-if="column.totalRows !== null" class="mt-1.5 text-caption text-ink-muted">
                    Across all {{ formatCount(column.totalRows) }} rows
                </p>
            </div>

            <div v-if="column.uniqueValues !== null" class="flex items-baseline justify-between gap-4 py-2.5">
                <dt class="text-ink-muted">Unique values</dt>
                <dd class="font-semibold tabular-nums text-ink">{{ formatCount(column.uniqueValues) }}</dd>
            </div>

            <div v-if="column.previewMissing || column.previewEmpty" class="flex items-baseline justify-between gap-4 py-2.5">
                <dt class="text-ink-muted">In this preview</dt>
                <dd class="text-right text-caption text-ink">
                    <span v-if="column.previewMissing" class="tabular-nums">{{ column.previewMissing }} null</span>
                    <span v-if="column.previewMissing && column.previewEmpty">, </span>
                    <span v-if="column.previewEmpty" class="tabular-nums">{{ column.previewEmpty }} empty</span>
                </dd>
            </div>

        </dl>

        <div v-if="column.sampleValues.length">
            <p class="mb-1.5 text-caption text-ink-muted">Sample values</p>
            <ul class="flex flex-wrap gap-1.5">
                <li v-for="(value, index) in column.sampleValues" :key="index"
                    class="max-w-full truncate rounded-[4px] border border-line bg-canvas px-1.5 py-0.5 font-mono text-caption text-ink"
                    :title="String(value)">
                    {{ formatSample(value) }}
                </li>
            </ul>
        </div>

        <p v-if="!hasStatistics" class="text-caption text-ink-muted">
            Column statistics are not available for this dataset right now.
        </p>

    </div>
</template>
