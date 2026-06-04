export function parseBackendTime(value: string | null | undefined): number | null {
  if (!value) {
    return null
  }
  const trimmed = value.trim()
  if (!trimmed) {
    return null
  }
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(trimmed)
  const normalized = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T')
  // Backend MySQL datetime values can be timezone-naive; treat them as UTC before displaying Shanghai time.
  const timestamp = Date.parse(hasTimezone ? normalized : `${normalized}Z`)
  return Number.isNaN(timestamp) ? null : timestamp
}

export function formatDateTimeShanghai(value: string | null | undefined): string {
  const timestamp = parseBackendTime(value)
  if (timestamp === null) {
    return '-'
  }
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(new Date(timestamp))
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  const hour = values.hour === '24' ? '00' : values.hour
  return `${values.year}-${values.month}-${values.day} ${hour}:${values.minute}:${values.second}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || ms < 0) {
    return '-'
  }
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) {
    return `${seconds}s`
  }
  const minutes = Math.floor(seconds / 60)
  const restSeconds = seconds % 60
  if (minutes < 60) {
    return `${minutes}m ${restSeconds}s`
  }
  const hours = Math.floor(minutes / 60)
  const restMinutes = minutes % 60
  return `${hours}h ${restMinutes}m`
}

export function elapsedBetween(start: string | null | undefined, end: string | null | undefined): string {
  const startTime = parseBackendTime(start)
  const endTime = parseBackendTime(end)
  if (startTime === null || endTime === null) {
    return '-'
  }
  return formatDuration(endTime - startTime)
}
