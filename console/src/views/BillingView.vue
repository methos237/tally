<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { api, cursorOf, unwrap } from '@/api/client'
import MoneyCell from '@/components/MoneyCell.vue'
import Pagination from '@/components/Pagination.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TallyTable from '@/components/TallyTable.vue'
import { formatDate } from '@/components/format'

const subscriptions = useQuery({
  queryKey: ['subscriptions'],
  queryFn: () => unwrap(api.GET('/api/subscriptions', { params: { query: { page_size: 500 } } })),
})
const subscriptionRows = computed(() =>
  (subscriptions.data.value?.results ?? []).map((s) => ({
    ...s,
    planText: `${s.plan_name} / ${s.interval}`,
    started: formatDate(s.started_at),
    billed: formatDate(s.billed_through),
  })),
)
const subscriptionColumns = [
  { key: 'customer', label: 'Customer' },
  { key: 'planText', label: 'Plan' },
  { key: 'amount', label: 'Amount', align: 'right' },
  { key: 'status', label: 'Status' },
  { key: 'started', label: 'Started' },
  { key: 'billed', label: 'Billed through' },
] as const

const status = ref<'' | 'open' | 'paid'>('')
const cursor = ref<string | undefined>()
const invoiceQuery = computed(() => ({
  status: status.value || undefined,
  cursor: cursor.value,
}))
const invoices = useQuery({
  queryKey: ['invoices', invoiceQuery],
  queryFn: () => unwrap(api.GET('/api/invoices', { params: { query: invoiceQuery.value } })),
})
const invoiceRows = computed(() =>
  (invoices.data.value?.results ?? []).map((i) => ({
    ...i,
    period: `${formatDate(i.period_start)} – ${formatDate(i.period_end)}`,
    issued: formatDate(i.issued_at),
  })),
)
const invoiceColumns = [
  { key: 'id', label: 'ID' },
  { key: 'customer', label: 'Customer' },
  { key: 'description', label: 'Description' },
  { key: 'period', label: 'Period' },
  { key: 'amount', label: 'Amount', align: 'right' },
  { key: 'status', label: 'Status' },
  { key: 'issued', label: 'Issued' },
] as const
</script>

<template>
  <h2 class="text-xl font-semibold">Subscriptions</h2>
  <TallyTable
    class="mt-4"
    :columns="[...subscriptionColumns]"
    :rows="subscriptionRows"
    row-key="id"
    caption="Subscriptions"
  >
    <template #cell-amount="{ row }"
      ><MoneyCell :amount="row.amount" :currency="row.currency"
    /></template>
    <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
  </TallyTable>

  <h2 class="mt-10 text-xl font-semibold">Invoices</h2>
  <label class="mt-3 flex items-center gap-2 text-sm">
    <span>Status</span>
    <select v-model="status" class="rounded border p-1" @change="cursor = undefined">
      <option value="">All</option>
      <option value="open">Open</option>
      <option value="paid">Paid</option>
    </select>
  </label>
  <TallyTable
    class="mt-3"
    :columns="[...invoiceColumns]"
    :rows="invoiceRows"
    row-key="id"
    caption="Invoices"
  >
    <template #cell-amount="{ row }"
      ><MoneyCell :amount="row.amount" :currency="row.currency"
    /></template>
    <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
  </TallyTable>
  <Pagination
    class="mt-3"
    :next="invoices.data.value?.next"
    :previous="invoices.data.value?.previous"
    @page="cursor = cursorOf($event)"
  />
</template>
