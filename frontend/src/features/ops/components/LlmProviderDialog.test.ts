import { flushPromises, mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import LlmProviderDialog from './LlmProviderDialog.vue'
import type { LlmProvider } from '@/shared/types/quant'

it('saves a changed API key without probing or discovering models', async () => {
  const provider: LlmProvider = { id: 'p', name: '测试供应商', protocol: 'openai_compatible', base_url: 'https://example.invalid/v1', key_last4: 'test', has_key: true, default_model: 'm', models: ['m'], model_catalog: [], models_synced_at: '', proxy_url: '', is_active: true, is_default: false, validated_at: '', note: '' }
  const wrapper = mount(LlmProviderDialog, { props: { open: true, provider }, global: { stubs: {
    ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
    ElSelect: { template: '<div><slot /></div>' }, ElOption: true, EmptyState: true,
  } } })
  try {
    await wrapper.find('input[type="password"]').setValue('fixture-new-key')
    await wrapper.findAll('button').find(b => b.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('save')?.[0]?.[0]).toMatchObject({ api_key: 'fixture-new-key', validate_key: false, discover_models: false })
  } finally { wrapper.unmount() }
})
