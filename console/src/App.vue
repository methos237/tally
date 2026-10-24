<script setup lang="ts">
import { useRouter } from 'vue-router'

import { pages } from '@/router'
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
    <div class="flex items-center gap-8">
      <h1 class="text-2xl font-semibold">Tally</h1>
      <nav v-if="session.current" aria-label="Main" class="flex gap-4 text-sm">
        <RouterLink
          v-for="page in pages"
          :key="page.name"
          :to="{ name: page.name }"
          class="text-slate-700 hover:underline"
          active-class="font-semibold text-slate-900 underline"
        >
          {{ page.label }}
        </RouterLink>
      </nav>
    </div>
    <div v-if="session.current" class="flex items-center gap-4 text-sm">
      <span class="text-slate-600"
        >{{ session.current.username }} · {{ session.current.tenant }}</span
      >
      <button type="button" class="underline" @click="signOut">Sign out</button>
    </div>
  </header>
  <main class="mx-auto max-w-6xl p-8 font-sans">
    <RouterView />
  </main>
</template>
