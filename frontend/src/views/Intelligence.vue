<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage, safeLink, statusLabel } from '../api'
import { chatIntegration, providerLabel, reasoningEffortLabel } from '../modelPresentation'
import type { AIResult, Integrations } from '../types'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'

const question = ref('')
const result = ref<AIResult | null>(null)
const integrations = ref<Integrations | null>(null)
const chat = computed(() => chatIntegration(integrations.value))
const busy = ref(false)
const error = ref('')
const examples = ['日本旅遊 7 天，有哪些套餐可以選擇？', '如何啟用 eSIM？', '實體 SIM 卡有哪些取卡方式？']
async function run() {
  if (!question.value.trim() || busy.value) return
  busy.value = true; error.value = ''; result.value = null
  try { result.value = await api<AIResult>('/ai/preview', 'POST', { question: question.value }) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
onMounted(async () => { try { integrations.value = await api<Integrations>('/integrations') } catch (err) { error.value = errorMessage(err) } })
</script>

<template>
  <div class="page-content ai-page"><div class="ai-intro"><div><span class="eyebrow">根據可信知識回答</span><h2>先看依據，再看回答。</h2><p>使用已發布知識與商品資料，測試對話模型的客服回覆。<br />這裡的結果只作預覽，不會傳送給客戶。</p></div><div class="ai-visual"><Icon name="sparkles" :size="42" /></div></div><div class="ai-grid"><section class="card ai-question"><div class="section-label"><h3><Icon name="inbox" :size="19" />模擬客戶問題</h3><span class="badge">僅預覽</span></div><form @submit.prevent="run"><label class="sr-only" for="ai-question">客戶問題</label><textarea id="ai-question" v-model="question" rows="6" placeholder="輸入客戶會問的問題，例如目的地、套餐或啟用方式…" required /><div class="question-examples"><small>試試這些問題</small><button v-for="example in examples" :key="example" type="button" @click="question = example">{{ example }}<Icon name="arrow" :size="13" /></button></div><button class="btn primary full" :disabled="busy || !question.trim()"><span v-if="busy" class="spinner small" /><Icon v-else name="sparkles" :size="17" />{{ busy ? '正在檢索與生成…' : '測試客服回答' }}</button></form><div class="ai-model-note"><span class="dot" :class="chat.configured ? 'teal' : 'amber'" /><span>{{ integrations ? chat.configured ? `對話模型：${chat.display_name || chat.model}` : '對話模型尚未配置' : '正在讀取模型配置…' }}</span></div><div v-if="integrations" class="ai-model-meta"><span>服務供應者：{{ providerLabel(chat.provider) }}</span><span :title="chat.reasoning_effort || undefined">推理強度：{{ reasoningEffortLabel(chat.reasoning_effort) }}</span><span v-if="chat.model && chat.display_name !== chat.model">模型識別：{{ chat.model }}</span></div></section><section class="card ai-response"><div class="section-label"><h3><Icon name="sparkles" :size="19" />回答與依據</h3><span v-if="result" class="badge" :class="result.status">{{ statusLabel(result.status) }}</span></div><div v-if="error" class="alert error" role="alert">{{ error }}</div><div v-if="busy" class="generating"><span class="spinner" /><h3>正在查找有依據的回答</h3><p>檢索已發布知識，並等待模型回應。</p></div><template v-else-if="result"><div class="answer-text">{{ result.answer || '未產生回答，請查看執行紀錄。' }}</div><div class="answer-sources"><h4>參考來源 <span>{{ result.citations.length }}</span></h4><a v-for="citation in result.citations" :key="citation.id" :href="safeLink(citation.url)" target="_blank" rel="noopener noreferrer"><span class="file-icon"><Icon name="file" :size="16" /></span><span>{{ citation.title }}<small>{{ citation.url || '本機知識文檔' }}</small></span><Icon name="external" :size="15" /></a><p v-if="!result.citations.length" class="muted small-text">本次沒有來源引用，請核對回覆狀態與執行紀錄。</p></div><details class="execution-trace" open><summary>執行紀錄 <span>{{ statusLabel(result.retrieval_mode) }}</span></summary><div v-for="(trace, index) in result.trace" :key="index"><span>{{ String(index + 1).padStart(2, '0') }}</span>{{ trace }}</div></details></template><EmptyState v-else-if="!error" title="回答將顯示在這裡" description="每次測試都會顯示實際回覆、來源引用與執行紀錄。服務不可用時會明確顯示錯誤。" icon="sparkles" /></section></div><div class="info-banner subtle-banner"><Icon name="info" :size="18" /><p>對話模型負責生成；向量模型負責檢索；重排模型負責排序。三項服務各自配置與驗證。</p></div></div>
</template>
