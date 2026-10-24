<script setup lang="ts">
import { computed } from 'vue'

import { formatMoney, type Currency } from './money'

const props = defineProps<{ amount: string; currency: Currency }>()
const text = computed(() => formatMoney(props.amount, props.currency))
const negative = computed(() => props.amount.startsWith('-'))
</script>

<template>
  <span
    class="tabular-nums"
    :class="negative ? 'text-red-700' : 'text-slate-900'"
    :title="`${amount} ${currency}`"
    >{{ text }}</span
  >
</template>
