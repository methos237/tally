<script setup lang="ts" generic="Row extends Record<string, unknown>">
import EmptyState from './EmptyState.vue'

export type Column<Row> = { key: keyof Row & string; label: string; align?: 'left' | 'right' }

defineProps<{
  columns: Column<Row>[]
  rows: Row[]
  rowKey: keyof Row & string
  caption: string
  emptyTitle?: string
}>()

const emit = defineEmits<{ select: [row: Row] }>()
</script>

<template>
  <EmptyState v-if="rows.length === 0" :title="emptyTitle ?? 'Nothing here yet'" />
  <table v-else class="w-full border-collapse text-sm">
    <caption class="sr-only">
      {{
        caption
      }}
    </caption>
    <thead>
      <tr class="border-b text-left text-slate-600">
        <th
          v-for="column in columns"
          :key="column.key"
          scope="col"
          class="py-2 pr-4 font-medium"
          :class="{ 'text-right': column.align === 'right' }"
        >
          {{ column.label }}
        </th>
      </tr>
    </thead>
    <tbody>
      <tr
        v-for="row in rows"
        :key="String(row[rowKey])"
        class="border-b hover:bg-slate-50"
        @click="emit('select', row)"
      >
        <td
          v-for="column in columns"
          :key="column.key"
          class="py-2 pr-4"
          :class="{ 'text-right': column.align === 'right' }"
        >
          <slot :name="`cell-${column.key}`" :row="row" :value="row[column.key]">
            {{ row[column.key] }}
          </slot>
        </td>
      </tr>
    </tbody>
  </table>
</template>
