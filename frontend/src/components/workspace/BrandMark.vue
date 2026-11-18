<script setup>
// =========================================================
// BRAND MARK
// =========================================================
//
// The product mark - an outlined four-point star in muted gold - with
// the product name. One component so the sidebar, mobile bar, drawer
// and sign-in screen can't drift apart.
//
// tone "forest": ivory name on a forest surface.
// tone "ivory":  ink name on ivory, star in forest (gold on ivory
//                fails contrast).

defineProps({
    tone: {
        type: String,
        default: "forest",
        validator: (value) => ["forest", "ivory"].includes(value),
    },
    // Show the tagline under the name.
    tagline: { type: Boolean, default: true },
    // Only the mark (e.g. a cramped mobile bar); the name stays for AT.
    compact: { type: Boolean, default: false },
});
</script>

<template>
    <span class="flex min-w-0 items-center" :class="tone === 'ivory' ? 'gap-2' : 'gap-3'">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke-linejoin="round"
            :class="tone === 'ivory' ? 'h-5 w-5 shrink-0 stroke-forest' : 'h-8 w-8 shrink-0 stroke-gold'"
            :stroke-width="tone === 'ivory' ? 1.8 : 1.5">
            <path
                d="M12 2.5c.7 4.6 2.8 7 8 9.5-5.2 2.5-7.3 4.9-8 9.5-.7-4.6-2.8-7-8-9.5 5.2-2.5 7.3-4.9 8-9.5Z" />
        </svg>
        <span class="min-w-0" :class="compact ? 'sr-only' : ''">
            <span class="block truncate font-semibold leading-tight tracking-[-0.01em]"
                :class="tone === 'ivory' ? 'text-body text-ink' : 'text-[17px] text-on-forest'">
                AI Data Intelligence
            </span>
            <span v-if="tagline" class="mt-1 block truncate text-caption"
                :class="tone === 'ivory' ? 'text-ink-muted' : 'text-on-forest-muted'">
                Data • Analyze • Understand
            </span>
        </span>
    </span>
</template>
