import type { Meta, StoryObj } from '@storybook/vue3-vite'

import Pagination from './Pagination.vue'

const meta: Meta<typeof Pagination> = { component: Pagination, title: 'Ledger/Pagination' }
export default meta
type Story = StoryObj<typeof meta>

export const Middle: Story = {
  args: { next: '/api/entries?cursor=next', previous: '/api/entries?cursor=prev' },
}
export const FirstPage: Story = { args: { next: '/api/entries?cursor=next', previous: null } }
