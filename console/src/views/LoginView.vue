<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSession } from '@/stores/session'

const session = useSession()
const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const busy = ref(false)

async function submit() {
  busy.value = true
  error.value = await session.login(username.value, password.value)
  busy.value = false
  if (!error.value) {
    const next = typeof route.query.next === 'string' ? route.query.next : '/'
    await router.replace(next)
  }
}
</script>

<template>
  <form class="mx-auto mt-16 flex max-w-sm flex-col gap-4" @submit.prevent="submit">
    <h2 class="text-xl font-semibold">Sign in</h2>
    <label class="flex flex-col gap-1">
      <span>Username</span>
      <input v-model="username" class="rounded border p-2" autocomplete="username" required />
    </label>
    <label class="flex flex-col gap-1">
      <span>Password</span>
      <input
        v-model="password"
        type="password"
        class="rounded border p-2"
        autocomplete="current-password"
        required
      />
    </label>
    <p v-if="error" role="alert" class="text-red-700">{{ error }}</p>
    <button type="submit" :disabled="busy" class="rounded bg-slate-900 px-4 py-2 text-white">
      Sign in
    </button>
  </form>
</template>
