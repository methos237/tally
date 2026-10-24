<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div data-empty class="rounded border border-dashed p-8 text-center text-slate-600">
    <p class="font-medium text-slate-800">{{ title }}</p>
    <p v-if="description" class="mt-1 text-sm">{{ description }}</p>
    <div v-if="$slots.default" class="mt-4"><slot /></div>
  </div>
</template>
