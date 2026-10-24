<script setup lang="ts">
import MoneyCell from './MoneyCell.vue'
import StatusBadge from './StatusBadge.vue'
import type { Currency } from './money'

export type ReconciliationException = {
  id: number
  line_no: number
  reference: string
  reason: string
  difference: string
  currency: Currency
  resolved_at?: string | null
  resolution?: string
  explanation?: string
}

defineProps<{ exception: ReconciliationException }>()
const emit = defineEmits<{ resolve: [exception: ReconciliationException] }>()
</script>

<template>
  <article class="rounded border p-4" :aria-labelledby="`exception-${exception.id}`">
    <header class="flex items-start justify-between gap-4">
      <h3 :id="`exception-${exception.id}`" class="font-medium">
        Line {{ exception.line_no }} · <span class="font-mono">{{ exception.reference }}</span>
      </h3>
      <StatusBadge :status="exception.resolved_at ? 'resolved' : 'open'" />
    </header>
    <p class="mt-2 text-sm text-slate-700">{{ exception.reason }}</p>
    <p class="mt-1 text-sm">
      Difference <MoneyCell :amount="exception.difference" :currency="exception.currency" />
    </p>
    <p v-if="exception.explanation" class="mt-1 text-sm text-slate-600">
      {{ exception.resolution }}: {{ exception.explanation }}
    </p>
    <button
      v-if="!exception.resolved_at"
      type="button"
      class="mt-3 rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
      @click="emit('resolve', exception)"
    >
      Resolve
    </button>
  </article>
</template>
