import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import DashboardView from '../views/DashboardView.vue'
import ReconciliationView from '../views/ReconciliationView.vue'
import WebhooksView from '../views/WebhooksView.vue'

type Route = (request: Request) => unknown

/** Stub fetch with a map of "METHOD /path" to a JSON body (or a function of the request). */
function stubApi(routes: Record<string, unknown | Route>) {
  const calls: Request[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof globalThis.fetch>(async (input) => {
      const request = input as Request
      calls.push(request)
      const url = new URL(request.url)
      const key = `${request.method} ${url.pathname}`
      const handler = routes[key]
      if (handler === undefined)
        return new Response(JSON.stringify({ detail: key }), { status: 404 })
      const body = typeof handler === 'function' ? (handler as Route)(request) : handler
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

function mountPage(component: Parameters<typeof mount>[0]) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      { path: '/billing', name: 'billing', component: { template: '<div />' } },
      { path: '/webhooks', name: 'webhooks', component: { template: '<div />' } },
      { path: '/reconciliation', name: 'reconciliation', component: { template: '<div />' } },
    ],
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(component, {
    global: { plugins: [createPinia(), router, [VueQueryPlugin, { queryClient }]] },
  })
}

beforeEach(() => {
  document.cookie = 'csrftoken=tok'
})

describe('DashboardView', () => {
  it('sums balances by type and counts open invoices, dead letters and exceptions', async () => {
    stubApi({
      'GET /api/accounts': {
        results: [
          {
            id: 1,
            code: '1000',
            name: 'Cash',
            type: 'asset',
            currency: 'USD',
            balance: '100.500000',
          },
          { id: 2, code: '1200', name: 'AR', type: 'asset', currency: 'USD', balance: '-0.500000' },
          {
            id: 3,
            code: '4000',
            name: 'Rev',
            type: 'revenue',
            currency: 'USD',
            balance: '-100.000000',
          },
        ],
      },
      'GET /api/invoices': { results: [{ id: 1 }, { id: 2 }] },
      'GET /api/webhook-endpoints': [
        { id: 1, dead_letters: 2 },
        { id: 2, dead_letters: 1 },
      ],
      'GET /api/reconciliation-exceptions': [{ id: 1 }],
    })
    const wrapper = mountPage(DashboardView)
    await flushPromises()
    expect(wrapper.find('dl').text()).toContain('asset$100.00')
    expect(wrapper.find('dl').text()).toContain('revenue-$100.00')
    expect(wrapper.get('[data-testid="open-invoices"]').text()).toBe('2')
    expect(wrapper.get('[data-testid="dead-letters"]').text()).toBe('3')
    expect(wrapper.get('[data-testid="open-exceptions"]').text()).toBe('1')
  })
})

describe('WebhooksView', () => {
  it('redelivers a dead letter with an Idempotency-Key and the CSRF header', async () => {
    const calls = stubApi({
      'GET /api/webhook-endpoints': [
        {
          id: 5,
          url: 'http://x/hook',
          created_at: '2026-01-01T00:00:00Z',
          disabled_at: null,
          dead_letters: 1,
        },
      ],
      'GET /api/webhook-endpoints/5/dead-letters': [
        {
          id: 9,
          event_type: 'invoice.paid',
          payload: {},
          created_at: '2026-01-01T00:00:00Z',
          attempts: 5,
          last_status: null,
          last_error: 'refused',
          dead_at: '2026-01-02T00:00:00Z',
        },
      ],
      'POST /api/webhook-endpoints/5/dead-letters/9/redeliver': { id: 9 },
    })
    const wrapper = mountPage(WebhooksView)
    await flushPromises()
    await wrapper.get('tbody tr').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('invoice.paid')
    await wrapper.get('button.text-xs').trigger('click')
    await flushPromises()
    const post = calls.find((r) => r.method === 'POST')!
    expect(post.url).toContain('/api/webhook-endpoints/5/dead-letters/9/redeliver')
    expect(post.headers.get('Idempotency-Key')).toMatch(/[0-9a-f-]{36}/)
    expect(post.headers.get('X-CSRFToken')).toBe('tok')
  })
})

describe('ReconciliationView', () => {
  it('shows lines beside exceptions and posts the resolution from the dialog', async () => {
    const exception = {
      id: 3,
      statement: 1,
      line_no: 2,
      reference: 'R2',
      reason: 'unmatched',
      difference: '-3.000000',
      currency: 'USD',
      entry: null,
      created_at: '2026-02-01T00:00:00Z',
      resolved_at: null,
    }
    const calls = stubApi({
      'GET /api/statements': [
        {
          id: 1,
          source: 'bank',
          period_start: '2026-02-01',
          period_end: '2026-02-28',
          uploaded_at: '2026-03-01T00:00:00Z',
          reconciled_at: '2026-03-01T00:00:00Z',
        },
      ],
      'GET /api/statements/1': {
        id: 1,
        source: 'bank',
        period_start: '2026-02-01',
        period_end: '2026-02-28',
        uploaded_at: '2026-03-01T00:00:00Z',
        reconciled_at: '2026-03-01T00:00:00Z',
        lines: [
          {
            line_no: 1,
            occurred_on: '2026-02-01',
            amount: '49.000000',
            currency: 'USD',
            reference: 'R1',
            description: '',
            matched_entry: 7,
            match_rule: 'exact',
          },
          {
            line_no: 2,
            occurred_on: '2026-02-02',
            amount: '-3.000000',
            currency: 'USD',
            reference: 'R2',
            description: 'fee',
            matched_entry: null,
            match_rule: '',
          },
        ],
        exceptions: [exception],
      },
      'GET /api/entries': {
        results: [
          {
            id: 7,
            occurred_at: '2026-02-01T09:00:00Z',
            source: { type: 'payment', id: 'p1' },
            lines: [{ account: '1000', amount: '49.000000', currency: 'USD' }],
          },
        ],
      },
      'POST /api/reconciliation-exceptions/3/resolve': {
        ...exception,
        resolved_at: '2026-03-02T00:00:00Z',
        resolution: 'explained',
      },
    })
    const wrapper = mountPage(ReconciliationView)
    await flushPromises()
    await wrapper.get('nav button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('#7 (exact)')
    await wrapper.get('article button').trigger('click') // Resolve on the ExceptionCard
    expect(wrapper.find('dialog').exists()).toBe(true)
    await flushPromises() // candidates load once the dialog is open
    expect(wrapper.get('dialog').text()).toContain('#7 2026-02-01 payment p1') // candidate within 3 days
    await wrapper.get('dialog textarea').setValue('Processor fee')
    await wrapper.get('dialog form').trigger('submit')
    await flushPromises()
    const post = calls.find((r) => r.method === 'POST')!
    expect(post.url).toContain('/api/reconciliation-exceptions/3/resolve')
    expect(await post.clone().json()).toEqual({ action: 'explain', explanation: 'Processor fee' })
    expect(wrapper.find('dialog').exists()).toBe(false)
  })
})
