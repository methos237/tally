<script setup lang="ts">
import { computed } from 'vue'

import MoneyCell from './MoneyCell.vue'
import type { components } from '@/api/schema'

export type Line = components['schemas']['LineOut']

const props = defineProps<{ lines: Line[] }>()

// Signed amounts: positive is a debit, negative a credit. Shown in the two classic columns.
const rows = computed(() =>
  props.lines.map((line) => ({
    ...line,
    debit: line.amount.startsWith('-') ? null : line.amount,
    credit: line.amount.startsWith('-') ? line.amount.slice(1) : null,
  })),
)
</script>

<template>
  <table class="w-full text-sm">
    <caption class="sr-only">
      Journal lines
    </caption>
    <thead>
      <tr class="border-b text-left text-slate-600">
        <th scope="col" class="py-1 pr-4 font-medium">Account</th>
        <th scope="col" class="py-1 pr-4 text-right font-medium">Debit</th>
        <th scope="col" class="py-1 text-right font-medium">Credit</th>
      </tr>
    </thead>
    <tbody>
      <tr v-for="(row, i) in rows" :key="i" class="border-b">
        <td class="py-1 pr-4 font-mono">{{ row.account }}</td>
        <td class="py-1 pr-4 text-right">
          <MoneyCell v-if="row.debit" :amount="row.debit" :currency="row.currency" />
        </td>
        <td class="py-1 text-right">
          <MoneyCell v-if="row.credit" :amount="row.credit" :currency="row.currency" />
        </td>
      </tr>
    </tbody>
  </table>
</template>
