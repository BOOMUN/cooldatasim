import assert from 'node:assert/strict'
import test from 'node:test'
import { chatIntegration, providerLabel, reasoningEffortLabel } from '../src/modelPresentation.ts'
import { diagnosticRows } from '../src/localization.ts'

test('new chat configuration is authoritative over the legacy Qwen alias', () => {
  const chat = { configured: true, provider: 'opencode', model: 'deepseek-v4.1-flash', reasoning_effort: 'high', display_name: 'DeepSeek V4.1 Flash' }
  const result = chatIntegration({ chat, qwen: { configured: true, model: 'legacy-qwen' } })
  assert.deepEqual(result, chat)
  assert.equal(providerLabel(result.provider), 'OpenCode')
  assert.equal(reasoningEffortLabel(result.reasoning_effort), '高')
})

test('an unconfigured chat never falsely falls back to a configured legacy alias', () => {
  const chat = { configured: false, provider: 'deepseek', model: 'selected-model', reasoning_effort: null, display_name: 'Selected Model' }
  assert.equal(chatIntegration({ chat, qwen: { configured: true, model: 'legacy-model' } }).configured, false)
  assert.equal(chatIntegration({ chat }).model, 'selected-model')
})

test('legacy responses still show the actual Qwen model without invented reasoning settings', () => {
  assert.deepEqual(chatIntegration({ qwen: { configured: true, model: 'legacy-qwen' } }), { configured: true, provider: 'qwen', model: 'legacy-qwen', reasoning_effort: null, display_name: 'legacy-qwen' })
  assert.equal(reasoningEffortLabel(null), '使用服務預設')
  assert.equal(providerLabel('deepseek'), 'DeepSeek')
  assert.equal(chatIntegration(null).configured, false)
  assert.equal(chatIntegration(null).model, '')
})

test('probe diagnostics omit duplicate Qwen aliases but preserve separate embedding and reranker roles', () => {
  const chat = { provider: 'opencode', model: 'deepseek-v4.1-flash', reasoning_effort: 'high' }
  const rows = diagnosticRows({ chat, qwen: chat, embedding: { model: 'Qwen3-Embedding-0.6B' }, reranker: { model: 'Qwen3-Reranker-0.6B' } })
  assert.equal(rows.filter(row => row.value === 'deepseek-v4.1-flash').length, 1)
  assert.deepEqual(rows.find(row => row.label === '對話模型 · 推理強度'), { label: '對話模型 · 推理強度', value: '高' })
  assert(rows.some(row => row.label === '向量模型 · 模型名稱' && row.value === 'Qwen3-Embedding-0.6B'))
  assert(rows.some(row => row.label === '重排模型 · 模型名稱' && row.value === 'Qwen3-Reranker-0.6B'))
  assert.deepEqual(diagnosticRows({ qwen: { model: 'legacy-qwen' } }), [{ label: '對話模型 · 模型名稱', value: 'legacy-qwen' }])
})
