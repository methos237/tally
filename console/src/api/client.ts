import createClient, { type Middleware } from 'openapi-fetch'

import type { paths } from './schema'

export function csrfToken(): string {
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

export type Problem = { type: string; title: string; status: number; detail: string }
