import type { ChatIntegration, Integrations } from './types'

export function chatIntegration(integrations: Pick<Integrations, 'chat' | 'qwen'> | null): ChatIntegration {
  if (integrations?.chat) return integrations.chat
  const legacy = integrations?.qwen
  return { configured: legacy?.configured ?? false, provider: legacy ? 'qwen' : '', model: legacy?.model ?? '', reasoning_effort: null, display_name: legacy?.model ?? '' }
}

export function providerLabel(value?: string | null): string {
  return value ? ({ opencode: 'OpenCode', deepseek: 'DeepSeek', qwen: 'Qwen', openai: 'OpenAI', evolution: 'Evolution', openai_compatible: '相容模型服務' } as Record<string, string>)[value.toLowerCase()] ?? value : '尚未指定'
}

export function reasoningEffortLabel(value?: string | null): string {
  return value ? ({ none: '停用', minimal: '最低', low: '低', medium: '中', high: '高', xhigh: '更高', max: '最高' } as Record<string, string>)[value] ?? '未識別設定' : '使用服務預設'
}
