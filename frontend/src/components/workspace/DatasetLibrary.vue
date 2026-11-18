<script setup>
import Icon from "../ui/Icon.vue";
import Tooltip from "../ui/Tooltip.vue";

// =========================================================
// DATASET LIBRARY (forest surface)
// =========================================================
//
// The signed-in user's datasets: select, delete, retry a failed load,
// add a new one. Purely presentational - Dashboard owns the dataset
// state and every handler; this renders props and emits intents.
//
// Lives inside the forest sidebar (laptop/desktop) and the forest
// navigation drawer (mobile), so it is styled for the forest world only.
//
// `touch` keeps the delete control always visible (no hover on touch
// screens); otherwise it appears on row hover / keyboard focus.

defineProps({
    datasets: { type: Array, required: true },
    isSelected: { type: Function, required: true },
    formatNumber: { type: Function, required: true },
    analysisMode: { type: String, required: true },
    analysisModeOptions: { type: Array, required: true },
    analysisModeLabel: { type: String, default: "" },
    selectedDatasetEntries: { type: Array, default: () => [] },
    selectedDatasetNames: { type: Array, default: () => [] },
    datasetsLoading: { type: Boolean, default: false },
    datasetsLoadError: { type: String, default: "" },
    deletingDatasetId: { type: String, default: "" },
    deleteError: { type: String, default: "" },
    touch: { type: Boolean, default: false },
});

const emit = defineEmits(["select", "delete", "retry", "upload", "set-mode"]);
</script>

<template>
    <section aria-labelledby="dataset-library-title" class="flex min-h-0 flex-col">

        <!-- Header: title, count, add -->

        <div class="flex shrink-0 items-center justify-between gap-2 pb-3 pl-5 pr-4">
            <h2 id="dataset-library-title" class="flex items-baseline gap-3 text-[15px] font-semibold text-on-forest">
                Datasets
                <span v-if="datasets.length" class="tabular-nums">
                    {{ datasets.length }}
                </span>
            </h2>

            <Tooltip content="Add dataset" side="right">
                <button type="button" aria-label="Add dataset" aria-haspopup="dialog"
                    class="grid h-8 w-8 place-items-center rounded-[8px] bg-forest-button text-on-forest shadow-[inset_0_1px_0_rgb(255_255_255/0.1)] transition-colors duration-150 hover:bg-forest-active"
                    @click="emit('upload')">
                    <Icon name="plus" :size="16" />
                </button>
            </Tooltip>
        </div>

        <!-- Analysis mode: only shown once more than one mode can run -->

        <div v-if="analysisModeOptions.length > 1" class="flex shrink-0 gap-0.5 px-3 pb-2" role="group"
            aria-label="Analysis mode">
            <button v-for="modeOption in analysisModeOptions" :key="modeOption.value" type="button"
                :aria-pressed="analysisMode === modeOption.value"
                class="rounded-control px-2 py-0.5 text-caption font-medium transition-colors duration-150"
                :class="analysisMode === modeOption.value ? 'bg-forest-raised text-on-forest' : 'text-on-forest-muted hover:text-on-forest'"
                @click="emit('set-mode', modeOption.value)">
                {{ modeOption.label }}
            </button>
        </div>

        <!-- List -->

        <div class="min-h-0 flex-1 overflow-y-auto px-3 [scrollbar-width:thin]">

            <p v-if="!datasets.length && datasetsLoading" role="status"
                class="flex items-center gap-2 px-2 py-2 text-data text-on-forest-muted">
                <span aria-hidden="true"
                    class="h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"></span>
                Loading datasets…
            </p>

            <div v-else-if="!datasets.length && !datasetsLoadError"
                class="mx-1 rounded-control border border-dashed border-forest-line px-3 py-4 text-data text-on-forest-muted">
                <p>No datasets yet.</p>
                <button type="button"
                    class="mt-1 font-semibold text-on-forest underline decoration-gold/70 underline-offset-4 hover:decoration-gold"
                    @click="emit('upload')">
                    Upload a CSV
                </button>
            </div>

            <div v-if="datasetsLoadError" role="alert"
                class="mx-1 mb-2 flex items-start gap-2 rounded-control bg-danger-soft px-2.5 py-2 text-caption text-danger">
                <Icon name="error" :size="14" class="mt-px" />
                <span class="min-w-0 flex-1">Couldn't load datasets: {{ datasetsLoadError }}</span>
                <button type="button" :disabled="datasetsLoading"
                    class="shrink-0 font-semibold underline underline-offset-2 disabled:opacity-60"
                    @click="emit('retry')">
                    {{ datasetsLoading ? 'Retrying…' : 'Retry' }}
                </button>
            </div>

            <ul class="space-y-0.5 pb-2">
                <li v-for="dataset in datasets" :key="dataset.dataset_id" class="group/row relative flex items-center">

                    <button type="button" :aria-current="isSelected(dataset.dataset_id) ? 'true' : undefined"
                        class="flex min-w-0 flex-1 items-center gap-3 rounded-[10px] py-2.5 pl-3 pr-10 text-left text-on-forest transition-colors duration-150"
                        :class="isSelected(dataset.dataset_id)
                            ? 'bg-forest-raised shadow-[inset_0_1px_0_rgb(255_255_255/0.06)]'
                            : 'hover:bg-white/5'"
                        @click="emit('select', dataset.dataset_id)">

                        <!-- Single mode: icon tile; other modes: checkbox -->
                        <span v-if="analysisMode === 'single'" aria-hidden="true"
                            class="grid h-6 w-6 shrink-0 place-items-center transition-colors duration-150"
                            :class="isSelected(dataset.dataset_id) ? 'text-gold' : 'text-on-forest-muted'">
                            <Icon name="table" :size="16" />
                        </span>
                        <span v-else aria-hidden="true"
                            class="grid h-4 w-4 shrink-0 place-items-center rounded-[3px] border"
                            :class="isSelected(dataset.dataset_id) ? 'border-gold bg-gold text-forest-deep' : 'border-on-forest-muted'">
                            <Icon v-if="isSelected(dataset.dataset_id)" name="check" :size="14" />
                        </span>

                        <span class="min-w-0 flex-1">
                            <span class="block truncate text-body font-semibold" :title="dataset.filename">
                                {{ dataset.filename }}
                            </span>
                            <span class="mt-0.5 block truncate text-caption tabular-nums text-on-forest/80">
                                {{ formatNumber(dataset.rows) }} rows • {{ formatNumber(dataset.columns) }} cols
                            </span>
                        </span>

                    </button>

                    <!-- Delete (sibling of the select button, never nested) -->
                    <button type="button" :disabled="deletingDatasetId === dataset.dataset_id"
                        :title="`Delete ${dataset.filename}`" :aria-label="`Delete ${dataset.filename}`"
                        class="absolute right-1.5 grid h-7 w-7 place-items-center rounded-control text-on-forest-muted transition hover:bg-danger-soft hover:text-danger focus-visible:opacity-100"
                        :class="touch || deletingDatasetId === dataset.dataset_id
                            ? 'opacity-100'
                            : 'opacity-0 group-hover/row:opacity-100'"
                        @click.stop="emit('delete', dataset)">
                        <span v-if="deletingDatasetId === dataset.dataset_id" aria-hidden="true"
                            class="h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent"></span>
                        <Icon v-else name="trash" :size="14" />
                    </button>

                </li>
            </ul>

            <p v-if="deleteError" role="alert"
                class="mx-1 mb-2 rounded-control bg-danger-soft px-2.5 py-2 text-caption text-danger">
                {{ deleteError }}
            </p>

        </div>

        <!-- Multi-dataset context (only for modes that select several) -->

        <div v-if="analysisMode !== 'single' && selectedDatasetEntries.length"
            class="shrink-0 border-t border-forest-line px-3 py-3">
            <p class="text-caption text-on-forest-muted">
                {{ analysisModeLabel }} mode, {{ selectedDatasetEntries.length }}
                dataset{{ selectedDatasetEntries.length === 1 ? '' : 's' }} selected
            </p>
            <p class="mt-0.5 truncate text-caption font-medium text-on-forest" :title="selectedDatasetNames.join(', ')">
                {{ selectedDatasetNames.join(', ') }}
            </p>
        </div>

    </section>
</template>
