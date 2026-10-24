<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { api, unwrap } from '@/api/client'
import MoneyCell from '@/components/MoneyCell.vue'
import type { Currency } from '@/components/money'

const accounts = useQuery({
  queryKey: ['accounts'],
  queryFn: () => unwrap(api.GET('/api/accounts', { params: { query: { page_size: 500 } } })),
})
const openInvoices = useQuery({
  queryKey: ['invoices', 'open'],
  queryFn: () =>
    unwrap(api.GET('/api/invoices', { params: { query: { status: 'open', page_size: 500 } } })),
})
const endpoints = useQuery({
  queryKey: ['webhook-endpoints'],
  queryFn: () => unwrap(api.GET('/api/webhook-endpoints')),
})
const exceptions = useQuery({
  queryKey: ['exceptions', 'open'],
  queryFn: () =>
    unwrap(api.GET('/api/reconciliation-exceptions', { params: { query: { status: 'open' } } })),
})

// Sum the projected balances per account type; the chart is single-currency per tenant.
const byType = computed(() => {
  const totals = new Map<string, { total: bigint; currency: Currency }>()
  for (const account of accounts.data.value?.results ?? []) {
    const micros = BigInt(account.balance.replace('.', ''))
    const row = totals.get(account.type) ?? { total: 0n, currency: account.currency }
    row.total += micros
    totals.set(account.type, row)
  }
  return [...totals].map(([type, { total, currency }]) => ({
    type,
    currency,
    balance: (total < 0n ? '-' : '') + micros(total < 0n ? -total : total),
  }))
})

function micros(value: bigint): string {
  const text = value.toString().padStart(7, '0')
  return `${text.slice(0, -6)}.${text.slice(-6)}`
}

const deadLetters = computed(() =>
  (endpoints.data.value ?? []).reduce((sum, endpoint) => sum + endpoint.dead_letters, 0),
)
</script>

<template>
  <h2 class="text-xl font-semibold">Dashboard</h2>
  <section class="mt-6 grid gap-6 md:grid-cols-3">
    <article class="rounded border p-4">
      <h3 class="font-medium">Balances by type</h3>
      <dl class="mt-2 space-y-1 text-sm">
        <div v-for="row in byType" :key="row.type" class="flex justify-between">
          <dt class="capitalize">{{ row.type }}</dt>
          <dd><MoneyCell :amount="row.balance" :currency="row.currency" /></dd>
        </div>
      </dl>
    </article>
    <article class="rounded border p-4">
      <h3 class="font-medium">Open invoices</h3>
      <p class="mt-2 text-3xl tabular-nums" data-testid="open-invoices">
        {{ openInvoices.data.value?.results.length ?? '…' }}
      </p>
      <RouterLink :to="{ name: 'billing' }" class="text-sm underline">Billing</RouterLink>
    </article>
    <article class="rounded border p-4">
      <h3 class="font-medium">Dead letters</h3>
      <p class="mt-2 text-3xl tabular-nums" data-testid="dead-letters">
        {{ endpoints.data.value ? deadLetters : '…' }}
      </p>
      <RouterLink :to="{ name: 'webhooks' }" class="text-sm underline">Webhooks</RouterLink>
    </article>
    <article class="rounded border p-4">
      <h3 class="font-medium">Open reconciliation exceptions</h3>
      <p class="mt-2 text-3xl tabular-nums" data-testid="open-exceptions">
        {{ exceptions.data.value?.length ?? '…' }}
      </p>
      <RouterLink :to="{ name: 'reconciliation' }" class="text-sm underline">Workbench</RouterLink>
    </article>
  </section>
</template>
