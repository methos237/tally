import type { Meta, StoryObj } from '@storybook/vue3-vite'

import JournalLines from './JournalLines.vue'

const meta: Meta<typeof JournalLines> = { component: JournalLines, title: 'Ledger/JournalLines' }
export default meta
type Story = StoryObj<typeof meta>

export const Invoice: Story = {
  args: {
    lines: [
      { account: '1200', amount: '49.000000', currency: 'USD' },
      { account: '4000', amount: '-49.000000', currency: 'USD' },
    ],
  },
}
