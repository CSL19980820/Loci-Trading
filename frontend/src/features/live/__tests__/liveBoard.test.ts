import { describe, expect, it } from 'vitest'
import { parseSseBlock } from '@/shared/api/marketStream'
import { formatTapeItem, computeHeatBuckets } from '@/shared/lib/tape'
import type { QuoteRow } from '@/shared/api/marketStream'

describe('marketStream SSE Block Parsing', () => {
  it('parses quote snapshot SSE block correctly', () => {
    const raw = `event: snapshot
id: 123
data: {"seq":1,"as_of":"2026-08-27T09:30:00","source":"tdx","session":{"phase":"morning","live":true},"rows":[{"code":"000001","name":"平安银行","price":12.5,"prev_close":12.0,"change":0.5,"pct":4.17,"volume":1000,"amount":12500,"turnover":1.2,"amplitude":4.5,"speed":0.1,"high":12.6,"low":12.0,"open":12.1,"stale_ms":10}]}`

    const parsed = parseSseBlock(raw)
    expect(parsed).not.toBeNull()
    expect(parsed?.type).toBe('snapshot')
    expect(parsed?.id).toBe('123')
    const data = parsed?.data as any
    expect(data.seq).toBe(1)
    expect(data.rows).toHaveLength(1)
    expect(data.rows[0].code).toBe('000001')
  })

  it('parses signal SSE block correctly', () => {
    const raw = `event: signal
data: {"seq":2,"as_of":"2026-08-27T09:31:00","items":[{"id":"sig_1","code":"600519","name":"贵州茅台","strategy":"dragon_head","strategy_name":"龙头突破","title":"放量突破","detail":"突破20日高点","direction":"long","strength":0.9,"price":1800,"pct":3.5,"provisional":true,"triggered_at":"2026-08-27T09:31:00"}]}`

    const parsed = parseSseBlock(raw)
    expect(parsed).not.toBeNull()
    expect(parsed?.type).toBe('signal')
    const data = parsed?.data as any
    expect(data.items).toHaveLength(1)
    expect(data.items[0].id).toBe('sig_1')
    expect(data.items[0].direction).toBe('long')
  })

  it('ignores comments and empty lines', () => {
    const raw = `: heartbeat comment`
    expect(parseSseBlock(raw)).toBeNull()
  })
})

describe('Tape and Heat calculations', () => {
  it('formats tape item with stable key', () => {
    const row1: QuoteRow = {
      code: '600000',
      name: '浦发银行',
      price: 10,
      prevClose: 9.8,
      change: 0.2,
      pct: 2.04,
      volume: 500,
      amount: 5000,
      turnover: 0.5,
      amplitude: 2.1,
      speed: 0.05,
      high: 10.1,
      low: 9.8,
      open: 9.9,
      staleMs: 5,
    }
    const item1 = formatTapeItem(row1)
    expect(item1.key).toBe('tape-600000')
    expect(item1.name).toBe('浦发银行')

    // 价格变动后 key 仍保持不变
    const row2 = { ...row1, price: 10.5, pct: 7.14 }
    const item2 = formatTapeItem(row2)
    expect(item2.key).toBe('tape-600000')
    expect(item2.price).toBe(10.5)
  })

  it('computes heat buckets distribution accurately', () => {
    const rows: QuoteRow[] = [
      {
        code: 'A',
        name: 'A',
        price: 10,
        prevClose: 11,
        change: -1,
        pct: -10,
        volume: 1,
        amount: 1,
        turnover: 1,
        amplitude: 1,
        speed: 0,
        high: 10,
        low: 10,
        open: 10,
        staleMs: 0,
      },
      {
        code: 'B',
        name: 'B',
        price: 10,
        prevClose: 10,
        change: 0,
        pct: 0,
        volume: 1,
        amount: 1,
        turnover: 1,
        amplitude: 1,
        speed: 0,
        high: 10,
        low: 10,
        open: 10,
        staleMs: 0,
      },
      {
        code: 'C',
        name: 'C',
        price: 11,
        prevClose: 10,
        change: 1,
        pct: 10,
        volume: 1,
        amount: 1,
        turnover: 1,
        amplitude: 1,
        speed: 0,
        high: 11,
        low: 11,
        open: 11,
        staleMs: 0,
      },
      {
        code: 'D',
        name: 'D',
        price: 10.2,
        prevClose: 10,
        change: 0.2,
        pct: 2.0,
        volume: 1,
        amount: 1,
        turnover: 1,
        amplitude: 1,
        speed: 0,
        high: 10.2,
        low: 10.2,
        open: 10.2,
        staleMs: 0,
      },
      {
        code: 'E',
        name: 'E',
        price: 9.6,
        prevClose: 10,
        change: -0.4,
        pct: -4.0,
        volume: 1,
        amount: 1,
        turnover: 1,
        amplitude: 1,
        speed: 0,
        high: 10,
        low: 9.6,
        open: 10,
        staleMs: 0,
      },
    ]

    const buckets = computeHeatBuckets(rows)
    expect(buckets).toHaveLength(11)

    const limitDown = buckets.find((b) => b.key === 'limitDown')
    const flat = buckets.find((b) => b.key === 'flat')
    const limitUp = buckets.find((b) => b.key === 'limitUp')
    const up1 = buckets.find((b) => b.key === 'up1')
    const down3 = buckets.find((b) => b.key === 'down3')

    expect(limitDown?.count).toBe(1)
    expect(flat?.count).toBe(1)
    expect(limitUp?.count).toBe(1)
    expect(up1?.count).toBe(1)
    expect(down3?.count).toBe(1)
  })
})
