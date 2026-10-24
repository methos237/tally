<script setup lang="ts">
defineOptions({ name: 'TallyPagination' })
// Cursor pagination: the API hands back full next/previous URLs or null.
defineProps<{ next?: string | null; previous?: string | null }>()
const emit = defineEmits<{ page: [url: string] }>()
</script>

<template>
  <nav aria-label="Pagination" class="flex gap-2 text-sm">
    <button
      type="button"
      class="rounded border px-3 py-1 disabled:opacity-40"
      :disabled="!previous"
      @click="previous && emit('page', previous)"
    >
      Previous
    </button>
    <button
      type="button"
      class="rounded border px-3 py-1 disabled:opacity-40"
      :disabled="!next"
      @click="next && emit('page', next)"
    >
      Next
    </button>
  </nav>
</template>
