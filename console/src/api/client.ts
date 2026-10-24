import createClient, { type Middleware } from 'openapi-fetch'

import type { paths } from './schema'

function csrfToken(): string {
  return document.cookie.match(/(?:^|; )csrftoken=([^;]*)/)?.[1] ?? ''
}

// Django's CsrfViewMiddleware wants the cookie echoed in a header on every unsafe method.
const csrf: Middleware = {
  onRequest({ request }) {
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method)) {
      request.headers.set('X-CSRFToken', csrfToken())
    }
    return request
  },
}

export const api = createClient<paths>({
  baseUrl: location.origin,
  credentials: 'same-origin',
  fetch: (request) => globalThis.fetch(request), // late-bound so tests can stub fetch
})
api.use(csrf)

/** Every write needs a fresh Idempotency-Key; a retry of the same user action reuses it. */
export function idempotencyKey(): { 'Idempotency-Key': string } {
  return { 'Idempotency-Key': crypto.randomUUID() }
}

/** openapi-fetch returns { data, error }; queries want data or a thrown Error. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call
  if (error !== undefined || data === undefined) {
    throw new Error((error as { detail?: string } | undefined)?.detail ?? response.statusText)
  }
  return data
}

/** DRF cursor pagination hands back full URLs; the query wants just the cursor. */
export function cursorOf(url: string | null | undefined): string | undefined {
  return url ? (new URL(url, location.origin).searchParams.get('cursor') ?? undefined) : undefined
}
