import { describe, expect, it } from 'vitest'

import {
  enabledModelOptions,
  formatContextWindow,
  formatModelLabel,
} from '@/shared/lib/llm'
import type { LlmProvider } from '@/shared/types/quant'

function provider(partial: Partial<LlmProvider>): LlmProvider {
  return {
    id: 'LLM1',
    name: 'demo',
    protocol: 'openai_compatible',
    base_url: 'https://example.com/v1',
    key_last4: '',
    has_key: true,
    default_model: '',
    models: [],
    model_catalog: [],
    models_synced_at: '',
    proxy_url: '',
    is_active: true,
    is_default: false,
    validated_at: '',
    note: '',
    ...partial,
  }
}

describe('llm helpers', () => {
  it('formats context windows', () => {
    expect(formatContextWindow(null)).toBe('')
    expect(formatContextWindow(512)).toBe('512')
    expect(formatContextWindow(65536)).toBe('66k')
    expect(formatContextWindow(1_000_000)).toBe('1M')
  })

  it('builds labels with context', () => {
    expect(
      formatModelLabel({ id: 'm1', name: 'Model One', context_window: 32000 }),
    ).toBe('Model One · m1 · 32k')
    expect(formatModelLabel({ id: 'm1', name: 'm1', context_window: null })).toBe('m1')
  })

  it('only exposes enabled catalog entries', () => {
    const options = enabledModelOptions(
      provider({
        models: ['on'],
        model_catalog: [
          {
            id: 'on',
            name: 'On',
            enabled: true,
            context_window: 8192,
            max_output_tokens: null,
            source: 'discovered',
          },
          {
            id: 'off',
            name: 'Off',
            enabled: false,
            context_window: null,
            max_output_tokens: null,
            source: 'manual',
          },
        ],
      }),
    )
    expect(options).toEqual([
      { value: 'on', label: 'On · on · 8k', context_window: 8192 },
    ])
  })

  it('falls back to models string list when catalog missing', () => {
    expect(
      enabledModelOptions(provider({ models: ['a', 'b'], model_catalog: [] })),
    ).toEqual([
      { value: 'a', label: 'a', context_window: null },
      { value: 'b', label: 'b', context_window: null },
    ])
  })
})
