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

        error.value =
            "Unable to load dataset metadata.";

    } finally {

        loading.value = false;
    }
}

onMounted(() => {
    loadMetadata();
});
</script>

<template>

    <section class="metadata">

        <h2>Dataset Schema</h2>

        <p v-if="loading">
            Loading schema...
        </p>

        <p v-else-if="error">
            {{ error }}
        </p>

        <div v-else-if="metadata" class="schema">

            <div v-for="(column, name) in metadata.columns" :key="name" class="column-card">

                <div class="column-header">

                    <strong>
                        {{ name }}
                    </strong>

                    <span>
                        {{ column.role }}
                    </span>

                </div>

                <p>
                    Type:
                    {{ column.data_type }}
                </p>

                <p>
                    Unique:
                    {{ column.unique_values }}
                </p>

                <p>
                    Missing:
                    {{ column.missing_count }}
                </p>

            </div>

        </div>

    </section>

</template>

<style scoped>
.metadata {
    padding: 24px;
}

.schema {
    display: grid;
    grid-template-columns:
        repeat(4, 1fr);

    gap: 16px;
}

.column-card {
    padding: 18px;
    border: 1px solid #ddd;
    border-radius: 12px;
}

.column-header {
    display: flex;
    justify-content: space-between;
    gap: 12px;
}

.column-header span {
    font-size: 12px;
}

.column-card p {
    margin-bottom: 6px;
}
</style>