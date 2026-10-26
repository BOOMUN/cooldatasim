<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { diagnosticRows } from '../localization'
import { chatIntegration, providerLabel, reasoningEffortLabel } from '../modelPresentation'
import type { Integrations, User } from '../types'
import Icon from '../components/Icon.vue'

const props = defineProps<{ kind: string; user: User }>()
const integrations = ref<Integrations | null>(null)
const chat = computed(() => chatIntegration(integrations.value))
const channel = ref<Record<string, unknown> | null>(null)
const status = ref<Record<string, unknown> | null>(null)
const probe = ref<Record<string, unknown> | null>(null)
const error = ref('')
const busy = ref(false)
const users = ref<User[]>([])
const userDialog = ref(false)
const userForm = ref({ username: '', display_name: '', role: 'agent', password: '' })
async function load() {
  busy.value = true; error.value = ''
  const results = await Promise.allSettled([api<Integrations>('/integrations'), props.kind === 'whatsapp' && props.user.role !== 'admin' ? Promise.resolve({ detail: '通道詳細診斷僅供管理員查看。' }) : api<Record<string, unknown>>(props.kind === 'whatsapp' ? '/whatsapp/status' : '/status')])
  if (results[0].status === 'fulfilled') integrations.value = results[0].value
  if (results[1].status === 'fulfilled') { if (props.kind === 'whatsapp') channel.value = results[1].value; else status.value = results[1].value }
  error.value = results.filter(result => result.status === 'rejected').map(result => errorMessage((result as PromiseRejectedResult).reason)).join('；')
  busy.value = false
}
async function checkModels() {
  busy.value = true; error.value = ''; probe.value = null
  try { probe.value = await api<Record<string, unknown>>('/ai/probe', 'POST') }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function loadUsers() {
  if (props.kind !== 'settings' || props.user.role !== 'admin') return
  try { users.value = await api<User[]>('/users') } catch (err) { error.value = errorMessage(err) }
}
function closeUserDialog() { userDialog.value = false; userForm.value = { username: '', display_name: '', role: 'agent', password: '' } }
async function createUser() {
  busy.value = true; error.value = ''
  try { await api('/users', 'POST', userForm.value); closeUserDialog(); await loadUsers() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
onMounted(() => { void load(); void loadUsers() })
</script>

<template>
  <div class="page-content settings-page"><div v-if="error" class="alert error" role="alert">{{ error }}</div><template v-if="kind === 'whatsapp'"><section class="card channel-overview"><div class="channel-brand"><Icon name="phone" :size="38" /></div><div><span class="eyebrow">商務訊息服務</span><h2>WhatsApp Business</h2><p>Evolution 關聯裝置方案 · 真實號碼同步待聯調</p></div><span class="badge amber">待驗證</span></section><div class="settings-grid"><section class="card settings-card"><h3>通道配置</h3><dl class="settings-list"><div><dt>接入服務</dt><dd>Evolution</dd></div><div><dt>憑證配置</dt><dd>{{ integrations ? integrations.whatsapp.configured ? '已配置 · 需驗證連通' : '尚未配置' : '讀取中…' }}</dd></div><div><dt>實例名稱</dt><dd>{{ integrations?.whatsapp.instance || '未設定' }}</dd></div><div><dt>真實外發</dt><dd>{{ integrations?.whatsapp.enabled ? '已開啟，依後端授權檢查' : '已停用' }}</dd></div></dl><button class="btn" :disabled="busy" @click="load"><Icon name="refresh" :size="16" />讀取通道狀態</button></section><section class="card settings-card"><h3>接入驗收範圍</h3><div class="verification-row"><span class="outline-dot" /><div><strong>掃碼關聯與雙向訊息</strong><p>需授權測試號碼並驗證真實訊息</p></div><span class="badge">待聯調</span></div><div class="verification-row"><span class="outline-dot" /><div><strong>媒體、引用與回執</strong><p>逐項核實通道支援與同步行為</p></div><span class="badge">待聯調</span></div><div class="verification-row"><span class="outline-dot" /><div><strong>歷史、編輯與撤回</strong><p>不能用掃碼成功代替功能驗收</p></div><span class="badge">待核實</span></div></section></div><section v-if="channel" class="card settings-card"><h3>最新狀態回應</h3><dl class="diagnostic-list"><div v-for="(row, index) in diagnosticRows(channel)" :key="index"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl></section></template>
    <template v-else><div class="info-banner"><Icon name="shield" :size="22" /><div><strong>模型配置與推理服務分開管理</strong><p>這裡僅顯示連線狀態。憑證由伺服器環境管理，不會下發至瀏覽器。</p></div></div><div class="model-grid"><section class="card model-card"><span class="model-step">01 / 生成回覆</span><div class="model-icon"><Icon name="sparkles" :size="25" /></div><h3>對話模型</h3><p>理解客戶問題，根據資料生成回覆。</p><strong class="model-name">{{ chat.display_name || chat.model || '尚未指定模型' }}</strong><dl class="model-details"><div v-if="chat.display_name && chat.model && chat.display_name !== chat.model"><dt>模型識別</dt><dd>{{ chat.model }}</dd></div><div><dt>服務供應者</dt><dd>{{ providerLabel(chat.provider) }}</dd></div><div><dt>推理強度</dt><dd :title="chat.reasoning_effort || undefined">{{ reasoningEffortLabel(chat.reasoning_effort) }}</dd></div></dl><span class="badge" :class="chat.configured ? 'configured' : 'amber'">{{ chat.configured ? '已配置 · 未代表健康' : '尚未配置' }}</span></section><section class="card model-card"><span class="model-step">02 / 向量檢索</span><div class="model-icon"><Icon name="book" :size="25" /></div><h3>Qwen 向量模型</h3><p>將問題與知識轉換成可檢索的向量。</p><strong class="model-name">{{ integrations?.embedding.model || '尚未指定模型' }}</strong><span class="badge" :class="integrations?.embedding.configured ? 'configured' : 'amber'">{{ integrations?.embedding.configured ? '已配置' : '尚未配置' }}</span><small class="muted">{{ integrations?.embedding.dimensions || '—' }} 維</small></section><section class="card model-card"><span class="model-step">03 / 資料重排</span><div class="model-icon"><Icon name="tag" :size="25" /></div><h3>Qwen 重排模型</h3><p>對候選資料重新排序，找到相關依據。</p><strong class="model-name">{{ integrations?.reranker.model || '尚未指定模型' }}</strong><span class="badge" :class="integrations?.reranker.configured ? 'configured' : 'amber'">{{ integrations?.reranker.configured ? '已配置' : '尚未配置' }}</span></section></div><div class="toolbar"><p class="muted small-text">連通檢查只讀取服務，不會啟動、切換或重啟模型。</p><button class="btn" :disabled="busy" @click="load"><Icon name="refresh" :size="16" />重新整理</button><button v-if="user.role === 'admin'" class="btn primary" :disabled="busy" @click="checkModels"><Icon name="globe" :size="16" />{{ busy ? '檢查中…' : '檢查模型連通' }}</button></div><section v-if="probe" class="card settings-card"><h3>本次連通檢查</h3><dl class="diagnostic-list"><div v-for="(row, index) in diagnosticRows(probe)" :key="index"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl></section><section v-if="status" class="card settings-card"><h3>本機服務狀態</h3><dl class="diagnostic-list"><div v-for="(row, index) in diagnosticRows(status)" :key="index"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl></section></template>
    <section v-if="kind === 'settings' && user.role === 'admin'" class="card settings-card"><div class="section-label"><h3>工作區成員</h3><button class="btn small" @click="userDialog = true; error = ''"><Icon name="plus" :size="16" />新增成員</button></div><table v-if="users.length"><thead><tr><th>名稱</th><th>帳號</th><th>角色</th></tr></thead><tbody><tr v-for="member in users" :key="member.id"><td><div class="person-cell"><span class="avatar small">{{ member.display_name.slice(0, 1) }}</span>{{ member.display_name }}</div></td><td>{{ member.username }}</td><td>{{ { admin: '管理員', agent: '客服人員', knowledge_manager: '知識管理員' }[member.role] || '未知角色' }}</td></tr></tbody></table></section>
  </div>
  <div v-if="userDialog" class="modal-backdrop" @click.self="!busy && closeUserDialog()"><section class="modal compact" role="dialog" aria-modal="true" aria-labelledby="member-title"><header><h2 id="member-title">新增工作區成員</h2><button class="icon-btn" aria-label="關閉" :disabled="busy" @click="closeUserDialog"><Icon name="close" /></button></header><form @submit.prevent="createUser"><div class="modal-body"><div v-if="error" class="alert error" role="alert">{{ error }}</div><label>顯示名稱<input v-model="userForm.display_name" required maxlength="160" autocomplete="off" /></label><label>登入帳號<input v-model="userForm.username" required minlength="3" maxlength="80" autocomplete="off" /></label><label>角色<select v-model="userForm.role"><option value="agent">客服人員 · 客戶與對話</option><option value="knowledge_manager">知識管理員 · 知識與商品審核</option><option value="admin">管理員 · 所有本機功能</option></select></label><label>初始密碼<input v-model="userForm.password" type="password" required minlength="16" maxlength="200" autocomplete="new-password" placeholder="至少 16 個字元" /></label><p class="muted small-text">新增成員會授予對應工作區權限，請核對帳號與角色後儲存。</p></div><footer><button type="button" class="btn" :disabled="busy" @click="closeUserDialog">取消</button><button class="btn primary" :disabled="busy">建立成員</button></footer></form></section></div>
</template>
