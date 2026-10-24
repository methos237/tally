import type { Meta, StoryObj } from '@storybook/vue3-vite'

import MoneyCell from './MoneyCell.vue'

const meta: Meta<typeof MoneyCell> = { component: MoneyCell, title: 'Ledger/MoneyCell' }
export default meta
type Story = StoryObj<typeof meta>

export const Debit: Story = { args: { amount: '1234.500000', currency: 'USD' } }
export const Credit: Story = { args: { amount: '-1234.500000', currency: 'EUR' } }
export const Yen: Story = { args: { amount: '98000.000000', currency: 'JPY' } }
