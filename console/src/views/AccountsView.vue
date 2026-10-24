<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { api, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import JournalLines from '@/components/JournalLines.vue'
import MoneyCell from '@/components/MoneyCell.vue'
import TallyTable from '@/components/TallyTable.vue'
import { formatDateTime } from '@/components/format'

type Account = components['schemas']['AccountOut']

const accounts = useQuery({
  queryKey: ['accounts'],
  queryFn: () => unwrap(api.GET('/api/accounts', { params: { query: { page_size: 500 } } })),
})
const columns = [
  { key: 'code', label: 'Code' },
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'balance', label: 'Balance', align: 'right' },
] as const

const selected = ref<Account | null>(null)
const asOf = ref('')
const code = computed(() => selected.value?.code ?? '')
const asOfIso = computed(() => (asOf.value ? `${asOf.value}T23:59:59Z` : undefined))

const history = useQuery({
  queryKey: ['balance', code, asOfIso],
  enabled: computed(() => !!selected.value && !!asOfIso.value),
  queryFn: () =>
    unwrap(
      api.GET('/api/accounts/{code}/balance', {
        params: { path: { code: code.value }, query: { as_of: asOfIso.value } },
      }),
    ),
})
const touching = useQuery({
  queryKey: ['entries', { account: code }],
  enabled: computed(() => !!selected.value),
  queryFn: () =>
    unwrap(api.GET('/api/entries', { params: { query: { account: code.value, page_size: 20 } } })),
})
</script>

<template>
  <h2 class="text-xl font-semibold">Accounts</h2>
  <div class="mt-4 grid gap-6" :class="selected ? 'lg:grid-cols-[1fr_1fr]' : ''">
    <TallyTable
      :columns="[...columns]"
      :rows="accounts.data.value?.results ?? []"
      row-key="code"
      caption="Chart of accounts"
      @select="selected = $event"
    >
      <template #cell-balance="{ row }">
        <MoneyCell :amount="row.balance" :currency="row.currency" />
      </template>
    </TallyTable>
    <aside v-if="selected" class="rounded border p-4" aria-label="Account history">
      <div class="flex items-start justify-between">
        <h3 class="font-medium">{{ selected.code }} {{ selected.name }}</h3>
        <button type="button" class="text-sm underline" @click="selected = null">Close</button>
      </div>
      <label class="mt-3 flex items-center gap-2 text-sm">
        <span>Balance as of</span>
        <input v-model="asOf" type="date" class="rounded border p-1" />
      </label>
      <p v-if="history.data.value" class="mt-2 text-sm" data-testid="as-of-balance">
        <MoneyCell :amount="history.data.value.balance" :currency="selected.currency" />
        at end of {{ asOf }}
      </p>
      <h4 class="mt-4 text-sm font-medium">Latest entries</h4>
      <ol class="mt-2 space-y-3 text-sm">
        <li v-for="entry in touching.data.value?.results ?? []" :key="entry.id">
          <p class="text-slate-600">
            #{{ entry.id }} · {{ formatDateTime(entry.occurred_at) }} · {{ entry.source.type }}
            {{ entry.source.id }}
          </p>
          <JournalLines :lines="entry.lines" />
        </li>
      </ol>
    </aside>
  </div>
</template>
