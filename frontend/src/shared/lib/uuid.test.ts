import { afterEach, expect, it, vi } from 'vitest'
import { createUuid } from './uuid'

afterEach(() => vi.unstubAllGlobals())

it('uses the native method with its Crypto receiver when available', () => {
  const native = { randomUUID() { expect(this).toBe(native); return 'a703b382-851b-4e34-a91b-03ba947164c3' } }
  vi.stubGlobal('crypto', native)
  expect(createUuid()).toBe('a703b382-851b-4e34-a91b-03ba947164c3')
})

it.each([0, 255])('preserves entropy outside UUID version/variant bits for byte %i', value => {
  vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(value) })
  expect(createUuid()).toBe(value === 0
    ? '00000000-0000-4000-8000-000000000000'
    : 'ffffffff-ffff-4fff-bfff-ffffffffffff')
})
