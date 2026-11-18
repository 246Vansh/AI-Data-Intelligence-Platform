<script>
import {
    ArrowDown,
    Bell,
    CircleCheck,
    Crown,
    Layers,
    Mic,
    Send,
    SlidersHorizontal,
    ArrowLeftRight,
    ArrowRight,
    ArrowUp,
    ChartColumn,
    Calendar,
    CaseSensitive,
    Check,
    ChevronDown,
    ChevronRight,
    CircleAlert,
    CircleHelp,
    Code,
    Columns3,
    Command,
    Copy,
    CornerDownLeft,
    Cpu,
    Database,
    Ellipsis,
    Eye,
    EyeOff,
    File,
    FileText,
    GripVertical,
    Hash,
    Info,
    LayoutGrid,
    Lightbulb,
    LogOut,
    Maximize2,
    Menu,
    MessageSquare,
    PanelLeft,
    PanelRight,
    Plus,
    RefreshCw,
    Rows3,
    Search,
    ShieldCheck,
    Sparkle,
    Table2,
    Target,
    ToggleLeft,
    TrendingUp,
    Trash2,
    TriangleAlert,
    Upload,
    User,
    X,
} from "@lucide/vue";

// =========================================================
// ICON SET (Lucide, behind the app's own icon names)
// =========================================================
//
// Phase 0 of the workspace redesign: the hand-drawn set is replaced by
// Lucide, but every call site keeps using these app-level names, so the
// library stays swappable. Each Lucide icon is imported individually
// (tree-shaken). Stroke is 1.5 and `non-scaling-stroke`, so every icon
// renders a 1.5px line at any size - the same rule as before.

export const ICONS = Object.freeze({
    // Actions
    check: Check,
    x: X,
    plus: Plus,
    upload: Upload,
    refresh: RefreshCw,
    search: Search,
    trash: Trash2,
    "log-out": LogOut,
    eye: Eye,
    "eye-off": EyeOff,

    // Direction
    "arrow-right": ArrowRight,
    "arrow-up": ArrowUp,
    "arrow-down": ArrowDown,
    "trend-up": TrendingUp,
    compare: ArrowLeftRight,
    "chevron-down": ChevronDown,
    "chevron-right": ChevronRight,

    // Navigation / layout
    overview: LayoutGrid,
    table: Table2,
    columns: Columns3,
    rows: Rows3,
    menu: Menu,
    "panel-left": PanelLeft,
    "panel-right": PanelRight,
    maximize: Maximize2,
    more: Ellipsis,
    grip: GripVertical,

    // Data
    database: Database,
    file: File,
    "file-text": FileText,
    copy: Copy,
    cpu: Cpu,
    "bar-chart": ChartColumn,
    code: Code,

    // Column types (Data workspace)
    "type-number": Hash,
    "type-text": CaseSensitive,
    "type-date": Calendar,
    "type-boolean": ToggleLeft,
    "type-other": CircleHelp,

    // Analysis
    sparkle: Sparkle,
    lightbulb: Lightbulb,
    message: MessageSquare,
    target: Target,
    "shield-check": ShieldCheck,

    // Status
    info: Info,
    error: CircleAlert,
    warning: TriangleAlert,

    // Keyboard / commands
    command: Command,
    enter: CornerDownLeft,

    // Account
    user: User,

    // Shell + Analyze (visual reference)
    bell: Bell,
    help: CircleHelp,
    "check-circle": CircleCheck,
    crown: Crown,
    layers: Layers,
    mic: Mic,
    send: Send,
    sliders: SlidersHorizontal,
});

export const ICON_SIZES = Object.freeze([14, 16, 20]);
</script>

<script setup>
import { computed } from "vue";

const props = defineProps({
    name: {
        type: String,
        required: true,
        validator: (value) => Object.hasOwn(ICONS, value),
    },
    size: {
        type: Number,
        default: 16,
        validator: (value) => ICON_SIZES.includes(value),
    },
    // Accessible name. Omit for decorative icons next to visible text
    // (the default); provide it when the icon alone carries meaning.
    label: {
        type: String,
        default: "",
    },
});

const component = computed(() => ICONS[props.name] || null);
</script>

<template>
    <component :is="component" v-if="component" :size="size" :stroke-width="1.5" non-scaling-stroke
        class="shrink-0" focusable="false" :role="label ? 'img' : undefined" :aria-label="label || undefined"
        :aria-hidden="label ? undefined : 'true'">
        <title v-if="label">{{ label }}</title>
    </component>
</template>
