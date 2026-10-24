import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '@/api/client'
import type { components } from '@/api/schema'

export type Session = components['schemas']['SessionOut']

export const useSession = defineStore('session', () => {
  const current = ref<Session | null>(null)
  const loaded = ref(false)

  // GET /console/session also sets the CSRF cookie the login POST needs.
  async function load(): Promise<Session | null> {
    const { data } = await api.GET('/console/session')
    current.value = data ?? null
    loaded.value = true
    return current.value
  }

  async function login(username: string, password: string): Promise<string | null> {
    const { data, error } = await api.POST('/console/login', { body: { username, password } })
    if (error) return error.detail
    current.value = data
    return null
  }

  async function logout(): Promise<void> {
    await api.POST('/console/logout')
    current.value = null
  }

  return { current, loaded, load, login, logout }
})
