/** Structural equality for BasicForm v-model sync (arrays/dates must not loop on new refs). */
export function formValuesEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true
  if (a == null || b == null) return a === b
  if (a instanceof Date && b instanceof Date) return a.getTime() === b.getTime()
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return false
    for (let i = 0; i < a.length; i += 1) {
      if (!formValuesEqual(a[i], b[i])) return false
    }
    return true
  }
  if (typeof a === 'object' && typeof b === 'object') {
    const aRec = a as Record<string, unknown>
    const bRec = b as Record<string, unknown>
    const aKeys = Object.keys(aRec)
    const bKeys = Object.keys(bRec)
    if (aKeys.length !== bKeys.length) return false
    for (const key of aKeys) {
      if (!Object.prototype.hasOwnProperty.call(bRec, key)) return false
      if (!formValuesEqual(aRec[key], bRec[key])) return false
    }
    return true
  }
  return false
}

export function formRecordsEqual(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const key of keys) {
    if (!formValuesEqual(a[key], b[key])) return false
  }
  return true
}
