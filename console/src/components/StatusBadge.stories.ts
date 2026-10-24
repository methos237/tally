import type { Meta, StoryObj } from '@storybook/vue3-vite'

import StatusBadge from './StatusBadge.vue'

const meta: Meta<typeof StatusBadge> = { component: StatusBadge, title: 'Ledger/StatusBadge' }
export default meta
type Story = StoryObj<typeof meta>

export const Active: Story = { args: { status: 'active' } }
export const PastDue: Story = { args: { status: 'past_due' } }
export const Open: Story = { args: { status: 'open' } }
export const Unknown: Story = { args: { status: 'something_else' } }
