import type { Meta, StoryObj } from '@storybook/vue3-vite'
import type { ConcreteComponent } from 'vue'

import TallyTable from './TallyTable.vue'

type Account = { code: string; name: string; type: string; balance: string }
const rows: Account[] = [
  { code: '1000', name: 'Cash', type: 'asset', balance: '12000.000000' },
  { code: '1200', name: 'Accounts receivable', type: 'asset', balance: '3400.250000' },
]
const columns = [
  { key: 'code', label: 'Code' },
  { key: 'name', label: 'Name' },
  { key: 'type', label: 'Type' },
  { key: 'balance', label: 'Balance', align: 'right' },
] as const

// Generic components do not fit Meta<typeof Component> yet; widen to Component.
const meta: Meta = { component: TallyTable as ConcreteComponent, title: 'Ledger/TallyTable' }
export default meta
type Story = StoryObj<typeof meta>

export const Accounts: Story = {
  args: { columns, rows, rowKey: 'code', caption: 'Accounts' },
}
export const Empty: Story = {
  args: {
    columns,
    rows: [],
    rowKey: 'code',
    caption: 'Accounts',
    emptyTitle: 'No accounts',
  },
}
