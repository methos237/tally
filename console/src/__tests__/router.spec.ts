import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import router from '../router'
import { useSession } from '../stores/session'

describe('router guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('sends a signed-out visitor to /login and remembers where they were going', async () => {
    const session = useSession()
    vi.spyOn(session, 'load').mockImplementation(async () => {
      session.loaded = true
      return null
    })
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.next).toBe('/')
  })

  it('keeps a signed-in operator off /login', async () => {
    const session = useSession()
    session.loaded = true
    session.current = { username: 'ops', tenant_id: 1, tenant: 'Acme Corp' }
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('dashboard')
  })
})
