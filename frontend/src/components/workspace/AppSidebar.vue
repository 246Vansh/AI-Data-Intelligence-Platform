<script setup>
import { computed } from "vue";

import Icon from "../ui/Icon.vue";
import { displayName, initials } from "../../services/userDisplay";
import AccountMenu from "./AccountMenu.vue";
import BrandMark from "./BrandMark.vue";
import ForestScene from "./ForestScene.vue";

// =========================================================
// APP SIDEBAR (forest)
// =========================================================
//
// The one navigation surface of the workspace: brand, the workspace
// sections (Analyze / Data / Schema / Quality - the `nav` slot, a
// <TabNav> owned by the Dashboard's Tabs root), the dataset library
// (default slot), a decorative pine ridge and the account at the
// bottom - laid out after the approved visual reference.
//
// Used docked on laptop/desktop and as the content of the mobile
// navigation drawer (where the `nav` slot is left empty, because the
// sections live in the top tabs / bottom bar there).

const props = defineProps({
    user: { type: Object, default: null },
    signingOut: { type: Boolean, default: false },
    // Brand row hidden when the host (mobile drawer) already shows it.
    showBrand: { type: Boolean, default: true },
});

const emit = defineEmits(["logout"]);

const name = computed(() => displayName(props.user));
const userInitials = computed(() => initials(props.user));
</script>

<template>
    <div
        class="theme-forest relative flex h-full min-h-0 flex-col overflow-hidden bg-[linear-gradient(180deg,#0f3123_0%,#173f2c_42%,#163c2a_70%,#0b291c_100%)] text-on-forest">

        <!-- Pine ridge above the account area (decorative) -->
        <div aria-hidden="true" class="pointer-events-none absolute inset-x-0 bottom-[68px] h-[190px]">
            <ForestScene />
        </div>

        <div class="relative flex min-h-0 flex-1 flex-col">

            <div v-if="showBrand" class="shrink-0 px-5 pb-6 pt-6">
                <BrandMark tone="forest" />
            </div>

            <div v-if="$slots.nav" class="shrink-0 px-3">
                <slot name="nav" />
            </div>

            <div v-if="$slots.nav" aria-hidden="true" class="mx-4 my-5 h-px shrink-0 bg-white/10"></div>

            <!-- Library; leaves room for the pine ridge below it -->
            <div class="flex min-h-0 flex-1 flex-col pb-[120px]">
                <slot />
            </div>

            <!-- Account -->

            <div v-if="user" class="relative shrink-0 border-t border-white/10 bg-[#0b291c]/70 px-3 py-3 backdrop-blur-[2px]">
                <AccountMenu :user="user" :signing-out="signingOut" side="top" align="start"
                    @logout="emit('logout')">
                    <button type="button" aria-label="Account menu"
                        class="flex w-full items-center gap-3 rounded-control p-1.5 text-left transition-colors duration-150 hover:bg-white/5 data-[state=open]:bg-white/5">
                        <span aria-hidden="true"
                            class="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[#a98a4f] text-data font-semibold text-[#fbf3df] ring-1 ring-[#d9bf86]/40">
                            {{ userInitials }}
                        </span>
                        <span class="min-w-0 flex-1">
                            <span class="block truncate text-body font-semibold text-on-forest">{{ name }}</span>
                            <span class="block truncate text-caption text-on-forest-muted">
                                {{ signingOut ? 'Signing out…' : user.email }}
                            </span>
                        </span>
                        <Icon name="chevron-down" :size="16" class="text-on-forest-muted" />
                    </button>
                </AccountMenu>
            </div>

        </div>

    </div>
</template>
