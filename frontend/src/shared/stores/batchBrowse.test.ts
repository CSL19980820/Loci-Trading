import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { parseBatchSource, toBatchItems, batchItemLabel, formatBatchPct } from '@/shared/lib/batchBrowse'
import { useBatchBrowseStore } from '@/shared/stores/batchBrowse'

describe('toBatchItems', () => {
  it('maps code/name/pct and drops empty codes', () => {
    expect(
      toBatchItems([
        { code: '600000', name: '浦发银行', pct: 1.2 },
        { code: '  ', name: 'x' },
        { code: '000001', changePct: -0.5 },
      ]),
    ).toEqual([
      { code: '600000', name: '浦发银行', pct: 1.2 },
      { code: '000001', name: undefined, pct: -0.5 },
    ])
  })
})

describe('formatBatchPct', () => {
  it('treats values as percentage points, not fractions', () => {
    expect(formatBatchPct(-0.71)).toBe('-0.71%')
    expect(formatBatchPct(1.23)).toBe('+1.23%')
    expect(formatBatchPct(0)).toBe('0.00%')
    expect(formatBatchPct(null)).toBe('')
  })
})

describe('batchItemLabel', () => {
  it('prefers name and strips a trailing code glued onto the name', () => {
    expect(batchItemLabel({ code: '000001', name: '平安银行' })).toBe('平安银行')
    expect(batchItemLabel({ code: '000001', name: '平安银行000001' })).toBe('平安银行')
    expect(batchItemLabel({ code: '000001', name: '平安银行 000001' })).toBe('平安银行')
    expect(batchItemLabel({ code: '000001' })).toBe('000001')
  })
})

describe('parseBatchSource', () => {
  it('splits strategy title and screen date', () => {
    expect(parseBatchSource('三源尾盘共振 · 2026-07-09')).toEqual({
      title: '三源尾盘共振',
      date: '2026-07-09',
      full: '三源尾盘共振 · 2026-07-09',
    })
    expect(parseBatchSource('选股结果').date).toBeNull()
  })
})

describe('useBatchBrowseStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
  })

  it('opens batch when at least two codes', () => {
    const store = useBatchBrowseStore()
    store.openBatch({
      source: '选股结果',
      sourcePath: '/screen',
      focusCode: '000002',
      items: [
        { code: '000001', name: '平安银行' },
        { code: '000002', name: '万科A' },
        { code: '000001', name: '重复' },
      ],
    })
    expect(store.active).toBe(true)
    expect(store.total).toBe(2)
    expect(store.index).toBe(1)
    expect(store.positionLabel).toBe('2/2')
    expect(store.current?.code).toBe('000002')
  })

  it('clears when fewer than two codes', () => {
    const store = useBatchBrowseStore()
    store.openBatch({
      source: '孤票',
      sourcePath: '/x',
      focusCode: '600000',
      items: [{ code: '600000' }],
    })
    expect(store.active).toBe(false)
    expect(store.session).toBeNull()
  })

  it('steps and syncs; clears when code leaves batch', () => {
    const store = useBatchBrowseStore()
    store.openBatch({
      source: '脉冲',
      sourcePath: '/pulse',
      focusCode: '600000',
      items: [{ code: '600000' }, { code: '600519' }, { code: '000858' }],
    })
    expect(store.step(1)).toBe('600519')
    expect(store.index).toBe(1)
    expect(store.step(-1)).toBe('600000')
    expect(store.goTo('000858')).toBe('000858')
    expect(store.positionLabel).toBe('3/3')

    store.syncCode('600519')
    expect(store.index).toBe(1)

    store.syncCode('999999')
    expect(store.active).toBe(false)
  })

  it('persists to sessionStorage', () => {
    const store = useBatchBrowseStore()
    store.openBatch({
      source: '行情台',
      sourcePath: '/data',
      focusCode: '1',
      items: [{ code: '1' }, { code: '2' }],
    })
    const raw = sessionStorage.getItem('loci.batchBrowse.v1')
    expect(raw).toBeTruthy()
    expect(JSON.parse(String(raw)).source).toBe('行情台')
  })
})
