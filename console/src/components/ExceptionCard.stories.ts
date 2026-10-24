import type { Meta, StoryObj } from '@storybook/vue3-vite'

import ExceptionCard from './ExceptionCard.vue'

const meta: Meta<typeof ExceptionCard> = { component: ExceptionCard, title: 'Ledger/ExceptionCard' }
export default meta
type Story = StoryObj<typeof meta>

const base = {
  id: 7,
  line_no: 12,
  reference: 'SETTLE-2026-09-14',
  reason: 'No journal entry within 3 days of 2026-09-14 for 1,240.00 USD',
  difference: '1240.000000',
  currency: 'USD' as const,
}

export const Open: Story = { args: { exception: base } }
export const Resolved: Story = {
  args: {
    exception: {
      ...base,
      resolved_at: '2026-10-01T09:00:00Z',
      resolution: 'explained',
      explanation: 'Processor fee netted in the next settlement',
    },
  },
}
