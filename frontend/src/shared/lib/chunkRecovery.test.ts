import { describe, expect, it } from 'vitest'
import { canRetryChunk, chunkAssetUrl, failedChunkAssets, isChunkLoadError } from './chunkRecovery'

describe('lazy resource recovery', () => {
  it.each([
    ['Failed to fetch dynamically imported module: https://example.test/assets/OpsView-A1.js', true],
    ['Importing a module script failed.', true],
    ['error loading dynamically imported module', true],
    ['Unable to preload CSS for /assets/OpsView-A.css', true],
    ['Loading chunk 21 failed', true],
    ['Cannot read properties of undefined', false],
    ['Failed to fetch', false],
  ])('classifies %s', (message, expected) => expect(isChunkLoadError(new TypeError(message))).toBe(expected))
  it.each([
    ['Failed to fetch dynamically imported module: https://example.test/assets/OpsView-A1.js','https://example.test/assets/OpsView-A1.js'],
    ['Unable to preload CSS for /assets/OpsView-A.css','https://example.test/assets/OpsView-A.css'],
    ['Failed to fetch dynamically imported module: https://other.test/assets/OpsView-A1.js',null],
    ['Failed to fetch dynamically imported module: https://example.test/api/admin.js',null],
    ['No resource URL',null],
  ])('only reloads same-origin asset paths', (error, expected) => expect(chunkAssetUrl(error, 'https://example.test')).toBe(expected))
  it('allows the first retry', () => expect(canRetryChunk(null, 100_000)).toBe(true))
  it('bounds repeated failures across page reloads', () => expect(canRetryChunk('{"at":90000}', 100_000)).toBe(false))
  it('allows explicit later recovery', () => expect(canRetryChunk('{"at":30000}', 100_000)).toBe(true))
  it('handles corrupt stored state', () => expect(canRetryChunk('bad json', 100_000)).toBe(true))
  it('handles clock changes', () => expect(canRetryChunk('{"at":200000}', 100_000)).toBe(true))
})


describe('cached nested dependency recovery', () => {
  it('refreshes a failed child even when the route error identifies its parent', () => {
    expect(failedChunkAssets([
      { name: 'https://example.test/assets/release-old.js', responseStatus: 404 },
      { name: 'https://example.test/assets/release-old.js', responseStatus: 404 },
      { name: 'https://example.test/assets/OpsView.js', responseStatus: 200 },
      { name: 'https://example.test/assets/missing.css', responseStatus: 503 },
      { name: 'https://example.test/api/missing.js', responseStatus: 404 },
      { name: 'https://other.test/assets/child.js', responseStatus: 404 },
    ], 'https://example.test')).toEqual([
      'https://example.test/assets/release-old.js', 'https://example.test/assets/missing.css',
    ])
  })
  it('does not invalidate successful or unknown responses', () => {
    expect(failedChunkAssets([{ name: 'https://example.test/assets/ok.js' },
      { name: 'https://example.test/assets/ok.js', responseStatus: 200 }], 'https://example.test')).toEqual([])
  })
})
