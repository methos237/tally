import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import EmptyState from '../EmptyState.vue'
import ExceptionCard from '../ExceptionCard.vue'
import JournalLines from '../JournalLines.vue'
import MoneyCell from '../MoneyCell.vue'
import Pagination from '../Pagination.vue'
import StatusBadge from '../StatusBadge.vue'
import TallyTable from '../TallyTable.vue'
import { formatMoney } from '../money'

describe('formatMoney', () => {
  it('formats decimal strings per currency without touching floats first', () => {
    expect(formatMoney('1234.500000', 'USD')).toBe('$1,234.50')
    expect(formatMoney('-1234.500000', 'EUR')).toBe('-€1,234.50')
    expect(formatMoney('98000.000000', 'JPY')).toBe('¥98,000')
    expect(formatMoney('0.000000', 'GBP')).toBe('£0.00')
    expect(formatMoney('123456789012.999999', 'USD')).toBe('$123,456,789,012.99')
  })
})

describe('MoneyCell', () => {
  it('marks credits red and keeps the raw amount in the title', () => {
    const wrapper = mount(MoneyCell, { props: { amount: '-5.000000', currency: 'USD' } })
    expect(wrapper.text()).toBe('-$5.00')
    expect(wrapper.classes()).toContain('text-red-700')
    expect(wrapper.attributes('title')).toBe('-5.000000 USD')
  })
})

describe('StatusBadge', () => {
  it('humanises the status and tones known ones', () => {
    const wrapper = mount(StatusBadge, { props: { status: 'past_due' } })
    expect(wrapper.text()).toBe('past due')
    expect(wrapper.classes()).toContain('text-red-800')
    expect(mount(StatusBadge, { props: { status: 'whatever' } }).classes()).toContain(
      'bg-slate-100',
    )
  })
})

describe('TallyTable', () => {
  const columns = [
    { key: 'code', label: 'Code' },
    { key: 'name', label: 'Name' },
  ] as const
  it('renders a header per column, a row per item, and emits the selected row', async () => {
    const rows = [{ code: '1000', name: 'Cash' }]
    const wrapper = mount(TallyTable, {
      props: { columns: [...columns], rows, rowKey: 'code', caption: 'Accounts' },
      slots: { 'cell-name': '<b>{{ params.value }}</b>' },
    })
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual(['Code', 'Name'])
    expect(wrapper.find('tbody b').text()).toBe('Cash')
    await wrapper.find('tbody tr').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[rows[0]]])
  })
  it('shows an empty state when there are no rows', () => {
    const wrapper = mount(TallyTable, {
      props: {
        columns: [...columns],
        rows: [],
        rowKey: 'code',
        caption: 'Accounts',
        emptyTitle: 'None',
      },
    })
    expect(wrapper.find('table').exists()).toBe(false)
    expect(wrapper.text()).toContain('None')
  })
})

describe('JournalLines', () => {
  it('splits signed amounts into debit and credit columns', () => {
    const wrapper = mount(JournalLines, {
      props: {
        lines: [
          { account: '1200', amount: '49.000000', currency: 'USD' },
          { account: '4000', amount: '-49.000000', currency: 'USD' },
        ],
      },
    })
    const cells = wrapper.findAll('tbody td').map((td) => td.text())
    expect(cells).toEqual(['1200', '$49.00', '', '4000', '', '$49.00'])
  })
})

describe('ExceptionCard', () => {
  const exception = {
    id: 1,
    line_no: 3,
    reference: 'REF',
    reason: 'why',
    difference: '10.000000',
    currency: 'USD' as const,
  }
  it('offers Resolve while open and emits the exception', async () => {
    const wrapper = mount(ExceptionCard, { props: { exception } })
    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('resolve')).toEqual([[exception]])
  })
  it('hides Resolve once resolved', () => {
    const wrapper = mount(ExceptionCard, {
      props: { exception: { ...exception, resolved_at: '2026-01-01T00:00:00Z' } },
    })
    expect(wrapper.find('button').exists()).toBe(false)
    expect(wrapper.text()).toContain('resolved')
  })
})

describe('Pagination', () => {
  it('disables missing directions and emits the cursor URL', async () => {
    const wrapper = mount(Pagination, { props: { next: '/api/x?cursor=n', previous: null } })
    const [previous, next] = wrapper.findAll('button')
    expect(previous!.attributes('disabled')).toBeDefined()
    await next!.trigger('click')
    expect(wrapper.emitted('page')).toEqual([['/api/x?cursor=n']])
  })
})

describe('EmptyState', () => {
  it('renders title, description and slot', () => {
    const wrapper = mount(EmptyState, {
      props: { title: 'Nothing', description: 'Yet' },
      slots: { default: '<a href="/">Go</a>' },
    })
    expect(wrapper.text()).toContain('Nothing')
    expect(wrapper.find('a').exists()).toBe(true)
  })
})
