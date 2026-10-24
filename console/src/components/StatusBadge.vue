<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const TONES: Record<string, string> = {
  active: 'bg-green-100 text-green-800',
  paid: 'bg-green-100 text-green-800',
  matched: 'bg-green-100 text-green-800',
  resolved: 'bg-green-100 text-green-800',
  delivered: 'bg-green-100 text-green-800',
  trialing: 'bg-blue-100 text-blue-800',
  open: 'bg-amber-100 text-amber-800',
  pending: 'bg-amber-100 text-amber-800',
  past_due: 'bg-red-100 text-red-800',
  failed: 'bg-red-100 text-red-800',
  dead: 'bg-red-100 text-red-800',
  canceled: 'bg-slate-200 text-slate-700',
  void: 'bg-slate-200 text-slate-700',
}

const tone = computed(() => TONES[props.status] ?? 'bg-slate-100 text-slate-700')
const label = computed(() => props.status.replace('_', ' '))
</script>

<template>
  <span class="inline-block rounded px-2 py-0.5 text-xs font-medium" :class="tone">{{
    label
  }}</span>
</template>
