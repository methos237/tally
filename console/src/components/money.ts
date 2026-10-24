import type { components } from '@/api/schema'

export type Currency = components['schemas']['CurrencyEnum']

/** Format a decimal string in its currency. Intl takes the string as-is, so the amount
 *  never passes through a float; extra places are truncated, not rounded. */
export function formatMoney(amount: string, currency: Currency): string {
  // roundingMode (Intl.NumberFormat v3) is not in the lib typings yet.
  const options = { style: 'currency', currency, roundingMode: 'trunc' } as Intl.NumberFormatOptions
  return new Intl.NumberFormat('en-US', options).format(amount as unknown as number)
}
