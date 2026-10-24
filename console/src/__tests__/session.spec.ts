import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useSession } from '../stores/session'

const SESSION = { username: 'ops', tenant_id: 1, tenant: 'Acme Corp' }

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    document.cookie = 'csrftoken=tok123'
  })

  it('load() records who is signed in', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(200, SESSION)))
    const session = useSession()
    expect(await session.load()).toEqual(SESSION)
    expect(session.loaded).toBe(true)
  })

  it('load() leaves current null on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(401, { detail: 'Not signed in' })))
    const session = useSession()
    expect(await session.load()).toBeNull()
    expect(session.loaded).toBe(true)
  })

  it('login() sends the CSRF cookie as a header and returns the problem detail on failure', async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValue(json(401, { detail: 'Wrong username or password' }))
    vi.stubGlobal('fetch', fetch)
    const session = useSession()
    expect(await session.login('ops', 'nope')).toBe('Wrong username or password')
    const request = fetch.mock.calls[0]![0] as Request
    expect(request.method).toBe('POST')
    expect(request.headers.get('X-CSRFToken')).toBe('tok123')
    expect(session.current).toBeNull()
  })

  it('login() then logout()', async () => {
    const fetch = vi
      .fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(json(200, SESSION))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetch)
    const session = useSession()
    expect(await session.login('ops', 'pw')).toBeNull()
    expect(session.current).toEqual(SESSION)
    await session.logout()
    expect(session.current).toBeNull()
  })
})
