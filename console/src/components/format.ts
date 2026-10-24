export function formatDate(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : ''
}

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 16).replace('T', ' ') + ' UTC' : ''
}
