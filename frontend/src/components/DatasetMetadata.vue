<script setup>
import { onMounted, ref } from "vue";
import axios from "axios";

const metadata = ref(null);
const loading = ref(true);
const error = ref(null);

async function loadMetadata() {
    try {
        const response = await axios.get(
            "http://127.0.0.1:8000/api/dataset/metadata"
        );

        metadata.value = response.data;
    } catch (err) {
        console.error(err);

        error.value = "Unable to load dataset metadata.";
    } finally {
        loading.value = false;
    }
}

onMounted(() => {
    loadMetadata();
});
</script>

<template>
    <section class="w-full p-6">
        <h2 class="mb-4 text-xl font-bold tracking-tight text-slate-900">
            Dataset Schema
        </h2>

        <p
            v-if="loading"
            class="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-500"
        >
            Loading schema...
        </p>

        <p
            v-else-if="error"
            class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700"
        >
            {{ error }}
        </p>

        <div
            v-else-if="metadata"
            class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
        >
            <div
                v-for="(column, name) in metadata.columns"
                :key="name"
                class="rounded-xl border border-slate-200 bg-white p-[18px] shadow-sm transition-shadow duration-200 hover:shadow-md"
            >
                <div class="flex items-center justify-between gap-3">
                    <strong
                        class="min-w-0 truncate text-sm font-semibold text-slate-900"
                    >
                        {{ name }}
                    </strong>

                    <span
                        class="shrink-0 rounded-full bg-violet-50 px-2 py-1 text-xs font-medium text-violet-700"
                    >
                        {{ column.role }}
                    </span>
                </div>

                <div class="mt-4 space-y-2">
                    <p class="mb-0 text-sm text-slate-600">
                        <span class="font-medium text-slate-800">
                            Type:
                        </span>
                        {{ column.data_type }}
                    </p>

                    <p class="mb-0 text-sm text-slate-600">
                        <span class="font-medium text-slate-800">
                            Unique:
                        </span>
                        {{ column.unique_values }}
                    </p>

                    <p class="mb-0 text-sm text-slate-600">
                        <span class="font-medium text-slate-800">
                            Missing:
                        </span>
                        {{ column.missing_count }}
                    </p>
                </div>
            </div>
        </div>
    </section>
</template>