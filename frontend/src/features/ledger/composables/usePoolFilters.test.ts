import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { usePoolFilters } from './usePoolFilters'

describe('candidate pool history scope', () => {
  it('defaults to excluding history and includes an enabled scope in the API filters', () => {
    const { filters, queryFilters } = usePoolFilters(ref([]))
    expect(queryFilters.value.include_backfill).toBe(false)
    filters.includeBackfill = true
    expect(queryFilters.value.include_backfill).toBe(true)
    filters.includeBackfill = false
    expect(queryFilters.value.include_backfill).toBe(false)
  })

  it('does not lose history scope when the three-field form emits its own values', () => {
    const { filters, filterModel, queryFilters, filterSchemas } = usePoolFilters(ref([]))
    filters.includeBackfill = true
    filterModel.value = { strategy: 'fixture-yang', decision: '精选', dateRange: ['2026-09-01', '2026-09-29'] }
    expect(queryFilters.value).toEqual({
      strategy: 'fixture-yang', decision: '精选', start: '2026-09-01', end: '2026-09-29',
      limit: 1000, include_backfill: true,
    })
    expect(filterSchemas.value.map(schema => schema.field)).toEqual(['strategy', 'decision', 'dateRange'])
  })
})
