export type Currency = 'USD' | 'EUR' | 'GBP' | 'JPY'

const formatters = new Map<Currency, Intl.NumberFormat>()

/** Format a decimal string (never a float: amounts travel as strings) in its currency. */
export function formatMoney(amount: string, currency: Currency): string {
  let formatter = formatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat('en-US', { style: 'currency', currency })
    formatters.set(currency, formatter)
  }
  const negative = amount.startsWith('-')
  const [whole = '0', fraction = ''] = (negative ? amount.slice(1) : amount).split('.')
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2
  const rounded = Number(`${whole}.${fraction.padEnd(digits, '0').slice(0, digits)}`)
  return (negative ? '-' : '') + formatter.format(rounded)
}
