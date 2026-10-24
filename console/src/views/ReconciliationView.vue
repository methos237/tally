<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, reactive, ref } from 'vue'

import { api, idempotencyKey, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import ExceptionCard, { type ReconciliationException } from '@/components/ExceptionCard.vue'
import MoneyCell from '@/components/MoneyCell.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TallyTable from '@/components/TallyTable.vue'
import { formatDate, formatDateTime } from '@/components/format'

const queryClient = useQueryClient()
const statements = useQuery({
  queryKey: ['statements'],
  queryFn: () => unwrap(api.GET('/api/statements')),
})
const statementId = ref<number | null>(null)
const statement = useQuery({
  queryKey: ['statement', statementId],
  enabled: computed(() => statementId.value !== null),
  queryFn: () =>
    unwrap(
      api.GET('/api/statements/{statement_id}', {
        params: { path: { statement_id: statementId.value! } },
      }),
    ),
})

const lineRows = computed(() =>
  (statement.data.value?.lines ?? []).map((l) => ({
    ...l,
    day: formatDate(l.occurred_on),
    match: l.matched_entry ? `#${l.matched_entry} (${l.match_rule})` : 'unmatched',
  })),
)
const lineColumns = [
  { key: 'line_no', label: '#', align: 'right' },
  { key: 'day', label: 'Date' },
  { key: 'reference', label: 'Reference' },
  { key: 'description', label: 'Description' },
  { key: 'amount', label: 'Amount', align: 'right' },
  { key: 'match', label: 'Match' },
] as const

const resolving = ref<ReconciliationException | null>(null)

// Candidates: cash entries within three days of the excepted line, the window the matcher uses.
const cash = useQuery({
  queryKey: ['entries', { account: '1000', page_size: 500 }],
  enabled: computed(() => resolving.value !== null),
  queryFn: () =>
    unwrap(api.GET('/api/entries', { params: { query: { account: '1000', page_size: 500 } } })),
})
const candidates = computed(() => {
  const line = statement.data.value?.lines.find((l) => l.line_no === resolving.value?.line_no)
  if (!line) return []
  const day = Date.parse(line.occurred_on)
  const window = 3 * 86_400_000
  return (cash.data.value?.results ?? []).filter(
    (e) => Math.abs(Date.parse(e.occurred_at) - day) <= window,
  )
})

function cashLine(entry: components['schemas']['EntryOut']) {
  return entry.lines.find((l) => l.account === '1000') ?? entry.lines[0]!
}

const form = reactive({ action: 'explain' as 'adjust' | 'explain', account: '', explanation: '' })
function openResolve(exception: ReconciliationException) {
  resolving.value = exception
  Object.assign(form, { action: 'explain', account: '', explanation: '' })
}

// After a write everything on screen may be stale (balances included); refetch it all.
const invalidate = () => queryClient.invalidateQueries()

const reconcile = useMutation({
  mutationFn: () =>
    unwrap(
      api.POST('/api/statements/{statement_id}/reconcile', {
        params: { path: { statement_id: statementId.value! }, header: idempotencyKey() },
      }),
    ),
  onSuccess: invalidate,
})

const resolve = useMutation({
  mutationFn: () =>
    unwrap(
      api.POST('/api/reconciliation-exceptions/{exception_id}/resolve', {
        params: { path: { exception_id: resolving.value!.id }, header: idempotencyKey() },
        body:
          form.action === 'adjust'
            ? { action: 'adjust', account: form.account }
            : { action: 'explain', explanation: form.explanation },
      }),
    ),
  onSuccess: () => {
    resolving.value = null
    invalidate()
  },
})
</script>

<template>
  <h2 class="text-xl font-semibold">Reconciliation workbench</h2>
  <div class="mt-4 grid gap-6 lg:grid-cols-[1fr_3fr]">
    <nav aria-label="Statements">
      <ul class="space-y-1 text-sm">
        <li v-for="s in statements.data.value ?? []" :key="s.id">
          <button
            type="button"
            class="w-full rounded border px-3 py-2 text-left hover:bg-slate-50"
            :class="{ 'border-slate-900': s.id === statementId }"
            :aria-pressed="s.id === statementId"
            @click="statementId = s.id"
          >
            <span class="font-medium">{{ s.source }}</span> {{ formatDate(s.period_start) }} –
            {{ formatDate(s.period_end) }}
            <StatusBadge class="ml-1" :status="s.reconciled_at ? 'matched' : 'open'" />
          </button>
        </li>
        <li v-if="statements.data.value?.length === 0" class="text-slate-600">No statements</li>
      </ul>
    </nav>

    <section v-if="statement.data.value" aria-label="Statement detail">
      <div class="flex items-center justify-between">
        <p class="text-sm text-slate-600">
          Uploaded {{ formatDateTime(statement.data.value.uploaded_at) }}
          <template v-if="statement.data.value.reconciled_at">
            · reconciled {{ formatDateTime(statement.data.value.reconciled_at) }}
          </template>
        </p>
        <button
          v-if="!statement.data.value.reconciled_at"
          type="button"
          class="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
          :disabled="reconcile.isPending.value"
          @click="reconcile.mutate()"
        >
          Reconcile
        </button>
      </div>
      <div class="mt-4 grid gap-6 xl:grid-cols-[3fr_2fr]">
        <TallyTable
          :columns="lineColumns"
          :rows="lineRows"
          row-key="line_no"
          caption="Statement lines"
        >
          <template #cell-amount="{ row }">
            <MoneyCell :amount="row.amount" :currency="row.currency" />
          </template>
        </TallyTable>
        <div class="space-y-3">
          <h3 class="font-medium">Exceptions</h3>
          <ExceptionCard
            v-for="exception in statement.data.value.exceptions"
            :key="exception.id"
            :exception="exception"
            @resolve="openResolve"
          />
          <p v-if="statement.data.value.exceptions.length === 0" class="text-sm text-slate-600">
            Every line matched or was explained.
          </p>
        </div>
      </div>
    </section>
  </div>

  <dialog
    v-if="resolving"
    open
    class="fixed inset-0 m-auto w-full max-w-lg rounded border p-6 shadow-lg"
    aria-labelledby="resolve-heading"
  >
    <h3 id="resolve-heading" class="font-medium">
      Resolve line {{ resolving.line_no }} · {{ resolving.reference }}
    </h3>
    <p class="mt-1 text-sm text-slate-700">
      {{ resolving.reason }} — difference
      <MoneyCell :amount="resolving.difference" :currency="resolving.currency" />
    </p>
    <section class="mt-3 text-sm" aria-label="Candidate entries">
      <h4 class="font-medium">Cash entries within 3 days</h4>
      <ul v-if="candidates.length" class="mt-1 space-y-1">
        <li v-for="e in candidates" :key="e.id" class="text-slate-700">
          #{{ e.id }} {{ formatDate(e.occurred_at) }} {{ e.source.type }} {{ e.source.id }}
          <MoneyCell :amount="cashLine(e).amount" :currency="cashLine(e).currency" />
        </li>
      </ul>
      <p v-else class="mt-1 text-slate-600">None</p>
    </section>
    <form class="mt-4 space-y-3 text-sm" @submit.prevent="resolve.mutate()">
      <fieldset class="flex gap-4">
        <legend class="sr-only">Resolution</legend>
        <label class="flex items-center gap-1">
          <input v-model="form.action" type="radio" value="explain" /> Explain
        </label>
        <label class="flex items-center gap-1">
          <input v-model="form.action" type="radio" value="adjust" /> Post adjusting entry
        </label>
      </fieldset>
      <label v-if="form.action === 'explain'" class="flex flex-col gap-1">
        <span>Explanation</span>
        <textarea v-model.trim="form.explanation" class="rounded border p-2" required rows="2" />
      </label>
      <label v-else class="flex flex-col gap-1">
        <span>Offset account code</span>
        <input v-model.trim="form.account" class="rounded border p-2" required placeholder="6100" />
      </label>
      <p v-if="resolve.error.value" role="alert" class="text-red-700">
        {{ resolve.error.value.message }}
      </p>
      <div class="flex justify-end gap-2">
        <button type="button" class="rounded border px-3 py-1.5" @click="resolving = null">
          Cancel
        </button>
        <button
          type="submit"
          class="rounded bg-slate-900 px-3 py-1.5 text-white"
          :disabled="resolve.isPending.value"
        >
          Resolve
        </button>
      </div>
    </form>
  </dialog>
</template>
