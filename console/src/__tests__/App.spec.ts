import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import HealthView from '../views/HealthView.vue'

describe('HealthView', () => {
  it('shows ok when the API answers', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
    const wrapper = mount(HealthView)
    await flushPromises()
    expect(wrapper.get('[data-testid="api-status"]').text()).toBe('API: ok')
  })

  it('shows down when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('refused')))
    const wrapper = mount(HealthView)
    await flushPromises()
    expect(wrapper.get('[data-testid="api-status"]').text()).toBe('API: down')
  })
})
