<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed, reactive, ref } from 'vue'

import { api, cursorOf, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import JournalLines from '@/components/JournalLines.vue'
import Pagination from '@/components/Pagination.vue'
import TallyTable from '@/components/TallyTable.vue'
import { formatDateTime } from '@/components/format'

type Entry = components['schemas']['EntryOut']

const draft = reactive({ source_type: '', source_id: '', account: '' })
const filters = ref({ ...draft })
const cursor = ref<string | undefined>()
const selected = ref<Entry | null>(null)

const query = computed(() => ({
  ...Object.fromEntries(Object.entries(filters.value).filter(([, v]) => v)),
  cursor: cursor.value,
}))
const entries = useQuery({
  queryKey: ['entries', query],
  queryFn: () => unwrap(api.GET('/api/entries', { params: { query: query.value } })),
})

const rows = computed(() =>
  (entries.data.value?.results ?? []).map((entry) => ({
    ...entry,
    occurred: formatDateTime(entry.occurred_at),
    sourceText: `${entry.source.type} ${entry.source.id}`,
    lineCount: entry.lines.length,
    flag: entry.reversed_by ? 'reversed' : entry.reverses ? 'reversal' : '',
  })),
)
const columns = [
  { key: 'id', label: 'ID' },
  { key: 'occurred', label: 'Occurred' },
  { key: 'sourceText', label: 'Source' },
  { key: 'lineCount', label: 'Lines', align: 'right' },
  { key: 'flag', label: '' },
] as const

function applyFilters() {
  filters.value = { ...draft }
  cursor.value = undefined
}
</script>

<template>
  <h2 class="text-xl font-semibold">Journal</h2>
  <form class="mt-4 flex flex-wrap items-end gap-3 text-sm" @submit.prevent="applyFilters">
    <label class="flex flex-col gap-1">
      <span>Source type</span>
      <input v-model.trim="draft.source_type" class="rounded border p-1" />
    </label>
    <label class="flex flex-col gap-1">
      <span>Source id</span>
      <input v-model.trim="draft.source_id" class="rounded border p-1" />
    </label>
    <label class="flex flex-col gap-1">
      <span>Account code</span>
      <input v-model.trim="draft.account" class="rounded border p-1" />
    </label>
    <button type="submit" class="rounded border px-3 py-1">Filter</button>
  </form>
  <div class="mt-4 grid gap-6" :class="selected ? 'lg:grid-cols-[2fr_1fr]' : ''">
    <div>
      <TallyTable
        :columns="columns"
        :rows="rows"
        row-key="id"
        caption="Journal entries"
        empty-title="No entries match"
        @select="selected = $event"
      />
      <Pagination
        class="mt-3"
        :next="entries.data.value?.next"
        :previous="entries.data.value?.previous"
        @page="cursor = cursorOf($event)"
      />
    </div>
    <aside v-if="selected" class="rounded border p-4" aria-label="Entry detail">
      <div class="flex items-start justify-between">
        <h3 class="font-medium">Entry {{ selected.id }}</h3>
        <button type="button" class="text-sm underline" @click="selected = null">Close</button>
      </div>
      <dl class="mt-2 text-sm text-slate-700">
        <div class="flex gap-2">
          <dt>Occurred</dt>
          <dd>{{ formatDateTime(selected.occurred_at) }}</dd>
        </div>
        <div class="flex gap-2">
          <dt>Posted</dt>
          <dd>{{ formatDateTime(selected.posted_at) }}</dd>
        </div>
        <div class="flex gap-2">
          <dt>Source</dt>
          <dd>{{ selected.source.type }} {{ selected.source.id }}</dd>
        </div>
        <div v-if="selected.reverses" class="flex gap-2">
          <dt>Reverses</dt>
          <dd>{{ selected.reverses }}</dd>
        </div>
        <div v-if="selected.reversed_by" class="flex gap-2">
          <dt>Reversed by</dt>
          <dd>{{ selected.reversed_by }}</dd>
        </div>
      </dl>
      <JournalLines class="mt-3" :lines="selected.lines" />
    </aside>
  </div>
</template>
