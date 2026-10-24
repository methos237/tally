import type { Meta, StoryObj } from '@storybook/vue3-vite'

import EmptyState from './EmptyState.vue'

const meta: Meta<typeof EmptyState> = { component: EmptyState, title: 'Ledger/EmptyState' }
export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {
  args: { title: 'No dead letters', description: 'Every webhook was delivered.' },
}
