<script setup lang="ts">
import { useSession } from '@/stores/session'

const session = useSession()
</script>

<template>
  <p class="mt-4" data-testid="tenant">Signed in to {{ session.current?.tenant }}</p>
</template>
