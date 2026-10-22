<script setup lang="ts">
import { onMounted, ref } from 'vue'

const status = ref<'loading' | 'ok' | 'down'>('loading')

onMounted(async () => {
  try {
    const response = await fetch('/health')
    status.value = response.ok ? 'ok' : 'down'
  } catch {
    status.value = 'down'
  }
})
</script>

<template>
  <p class="mt-4" data-testid="api-status">API: {{ status }}</p>
</template>
