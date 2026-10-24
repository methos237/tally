<script setup lang="ts">
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'

import { api, idempotencyKey, unwrap } from '@/api/client'
import type { components } from '@/api/schema'
import StatusBadge from '@/components/StatusBadge.vue'
import TallyTable from '@/components/TallyTable.vue'
import { formatDateTime } from '@/components/format'

type Endpoint = components['schemas']['WebhookEndpointOut']

const queryClient = useQueryClient()
const endpoints = useQuery({
  queryKey: ['webhook-endpoints'],
  queryFn: () => unwrap(api.GET('/api/webhook-endpoints')),
})
const endpointRows = computed(() =>
  (endpoints.data.value ?? []).map((e) => ({
    ...e,
    state: e.disabled_at ? 'disabled' : 'active',
    created: formatDateTime(e.created_at),
  })),
)
const endpointColumns = [
  { key: 'id', label: 'ID' },
  { key: 'url', label: 'URL' },
  { key: 'state', label: 'State' },
  { key: 'dead_letters', label: 'Dead letters', align: 'right' },
  { key: 'created', label: 'Created' },
] as const

const selected = ref<Endpoint | null>(null)
const endpointId = computed(() => selected.value?.id ?? 0)
const deadLetters = useQuery({
  queryKey: ['dead-letters', endpointId],
  enabled: computed(() => !!selected.value),
  queryFn: () =>
    unwrap(
      api.GET('/api/webhook-endpoints/{endpoint_id}/dead-letters', {
        params: { path: { endpoint_id: endpointId.value } },
      }),
    ),
})
const deadRows = computed(() =>
  (deadLetters.data.value ?? []).map((m) => ({
    ...m,
    died: formatDateTime(m.dead_at),
    redeliver: '',
    last: m.last_status ? String(m.last_status) : m.last_error || '—',
  })),
)
const deadColumns = [
  { key: 'id', label: 'ID' },
  { key: 'event_type', label: 'Event' },
  { key: 'attempts', label: 'Attempts', align: 'right' },
  { key: 'last', label: 'Last result' },
  { key: 'died', label: 'Dead since' },
  { key: 'redeliver', label: '' },
] as const

const redeliver = useMutation({
  mutationFn: (messageId: number) =>
    unwrap(
      api.POST('/api/webhook-endpoints/{endpoint_id}/dead-letters/{message_id}/redeliver', {
        params: {
          path: { endpoint_id: endpointId.value, message_id: messageId },
          header: idempotencyKey(),
        },
      }),
    ),
  onSuccess: () => queryClient.invalidateQueries(),
})
</script>

<template>
  <h2 class="text-xl font-semibold">Webhook endpoints</h2>
  <TallyTable
    class="mt-4"
    :columns="endpointColumns"
    :rows="endpointRows"
    row-key="id"
    caption="Webhook endpoints"
    empty-title="No endpoints registered"
    @select="selected = $event"
  >
    <template #cell-state="{ row }"><StatusBadge :status="row.state" /></template>
  </TallyTable>

  <section v-if="selected" class="mt-8" aria-labelledby="dead-letters-heading">
    <h3 id="dead-letters-heading" class="font-medium">Dead letters for {{ selected.url }}</h3>
    <p v-if="redeliver.error.value" role="alert" class="mt-2 text-sm text-red-700">
      {{ redeliver.error.value.message }}
    </p>
    <TallyTable
      class="mt-3"
      :columns="deadColumns"
      :rows="deadRows"
      row-key="id"
      caption="Dead letters"
      empty-title="No dead letters"
    >
      <template #cell-redeliver="{ row }">
        <button
          type="button"
          class="rounded border px-2 py-0.5 text-xs"
          :disabled="redeliver.isPending.value"
          @click.stop="redeliver.mutate(row.id)"
        >
          Redeliver
        </button>
      </template>
    </TallyTable>
  </section>
</template>
