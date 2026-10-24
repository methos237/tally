<script setup lang="ts">
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'

import { api, unwrap } from '@/api/client'
import TallyTable from '@/components/TallyTable.vue'
import { formatDateTime } from '@/components/format'

const reports = useQuery({
  queryKey: ['reports'],
  queryFn: () => unwrap(api.GET('/api/reports')),
})
const rows = computed(() =>
  (reports.data.value ?? []).map((r) => ({
    ...r,
    kilobytes: `${(r.size / 1024).toFixed(1)} KB`,
    written: formatDateTime(r.last_modified),
  })),
)
const columns = [
  { key: 'day', label: 'Day' },
  { key: 'kilobytes', label: 'Size', align: 'right' },
  { key: 'written', label: 'Written' },
  { key: 'key', label: 'Download' },
] as const
</script>

<template>
  <h2 class="text-xl font-semibold">Partner daily reports</h2>
  <TallyTable
    class="mt-4"
    :columns="columns"
    :rows="rows"
    row-key="day"
    caption="Reports"
    empty-title="No reports yet"
  >
    <template #cell-key="{ row }">
      <a :href="`/api/reports/${row.day}`" download class="underline">{{ row.day }}.csv</a>
    </template>
  </TallyTable>
</template>
