<script setup lang="ts">
import { useRouter } from 'vue-router'

import { useSession } from '@/stores/session'

const session = useSession()
const router = useRouter()

async function signOut() {
  await session.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <header class="flex items-center justify-between border-b px-8 py-4">
    <h1 class="text-2xl font-semibold">Tally</h1>
    <nav v-if="session.current" class="flex items-center gap-4">
      <span class="text-slate-600"
        >{{ session.current.username }} · {{ session.current.tenant }}</span
      >
      <button type="button" class="underline" @click="signOut">Sign out</button>
    </nav>
  </header>
  <main class="mx-auto max-w-5xl p-8 font-sans">
    <RouterView />
  </main>
</template>
