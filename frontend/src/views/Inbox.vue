<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, dateTime, errorMessage, statusLabel } from '../api'
import { languageLabel, messageKindLabel } from '../localization'
import type { AIResult, Conversation, User } from '../types'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps<{ user: User; initialId: number | null }>()
const items = ref<Conversation[]>([])
const current = ref<Conversation | null>(null)
const users = ref<User[]>([])
const query = ref('')
const view = ref('all')
const busy = ref(false)
const loading = ref(true)
const error = ref('')
const text = ref('')
const replyType = ref('reply')
const simulatedText = ref('')
const suggestion = ref<AIResult | null>(null)
const messageArea = ref<HTMLElement | null>(null)
const tabs = [{ id: 'all', label: '全部' }, { id: 'unread', label: '未讀' }, { id: 'mine', label: '我的' }, { id: 'unassigned', label: '未分配' }]
const selectedUser = computed({ get: () => current.value?.assigned_user_id ?? '', set: value => void change({ assigned_user_id: value === '' ? null : Number(value) }) })
let poll: ReturnType<typeof setInterval> | undefined
let debounce: ReturnType<typeof setTimeout> | undefined
let loadSequence = 0
let openSequence = 0
let pendingSend: { signature: string; key: string } | null = null

async function load(quiet = false) {
  const sequence = ++loadSequence
  if (!quiet) loading.value = true
  try { const response = await api<Conversation[]>(`/conversations?q=${encodeURIComponent(query.value)}&view=${view.value}`); if (sequence === loadSequence) items.value = response }
  catch (err) { error.value = errorMessage(err) }
  finally { if (sequence === loadSequence) loading.value = false }
}
async function open(id: number, quiet = false) {
  const sequence = ++openSequence
  try {
    const conversation = await api<Conversation>(`/conversations/${id}`)
    if (sequence !== openSequence) return
    current.value = conversation
    if (!quiet) { text.value = ''; suggestion.value = null; error.value = ''; replyType.value = 'reply'; await api(`/conversations/${id}/read`, 'POST'); void load(true); setTimeout(() => { messageArea.value?.scrollTo({ top: messageArea.value.scrollHeight }) }, 20) }
  } catch (err) { error.value = errorMessage(err) }
}
async function sandbox() {
  busy.value = true; error.value = ''
  try { const conversation = await api<Conversation>('/sandbox', 'POST'); await load(); await open(conversation.id) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function change(body: Record<string, unknown>) {
  if (!current.value) return
  const id = current.value.id
  busy.value = true; error.value = ''
  try { await api(`/conversations/${id}`, 'PATCH', body); await open(id, true); await load(true) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function send() {
  if (!text.value.trim() || !current.value || busy.value) return
  const id = current.value.id
  const body = text.value.trim()
  const internal = replyType.value === 'note'
  const signature = JSON.stringify([id, body, internal])
  if (pendingSend?.signature !== signature) pendingSend = { signature, key: crypto.randomUUID() }
  const idempotencyKey = pendingSend.key
  busy.value = true; error.value = ''
  try { await api(`/conversations/${id}/messages`, 'POST', { body, internal, idempotency_key: idempotencyKey }); pendingSend = null; if (current.value?.id === id) { text.value = ''; await open(id, true) }; await load(true); setTimeout(() => messageArea.value?.scrollTo({ top: messageArea.value.scrollHeight, behavior: 'smooth' }), 20) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function simulate() {
  if (!simulatedText.value.trim() || !current.value || busy.value) return
  busy.value = true; error.value = ''
  try { await api(`/conversations/${current.value.id}/simulate`, 'POST', { body: simulatedText.value }); simulatedText.value = ''; await open(current.value.id, true); await load(true) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function suggest() {
  if (!current.value) return
  const id = current.value.id
  busy.value = true; error.value = ''; suggestion.value = null
  try { const result = await api<AIResult>(`/conversations/${id}/suggest`, 'POST'); if (current.value?.id === id) suggestion.value = result }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
watch([query, view], () => { clearTimeout(debounce); debounce = setTimeout(() => void load(), 250) })
watch(() => props.initialId, id => { if (id) void open(id) })
onMounted(async () => { await load(); try { users.value = await api<User[]>('/users') } catch (err) { error.value = errorMessage(err) } if (props.initialId) await open(props.initialId); poll = setInterval(() => { void load(true); if (current.value) void open(current.value.id, true) }, 6000) })
onBeforeUnmount(() => { clearInterval(poll); clearTimeout(debounce); loadSequence++; openSequence++ })
</script>

<template>
  <div class="inbox-layout" :class="{ 'conversation-open': current }">
    <section class="conversation-list"><div class="list-heading"><h1>收件匣 <span class="count-badge">{{ items.length }}</span></h1><button class="icon-btn" title="重新整理" aria-label="重新整理會話" @click="load()"><Icon name="refresh" :size="18" /></button></div><div class="search-field"><Icon name="search" :size="18" /><input v-model="query" aria-label="搜尋對話" placeholder="搜尋客戶或對話…" /></div><div class="conversation-tabs"><button v-for="tab in tabs" :key="tab.id" :class="{ active: view === tab.id }" @click="view = tab.id">{{ tab.label }}</button></div><div class="conversation-items"><div v-if="loading" class="loading-line">正在載入對話…</div><button v-for="item in items" :key="item.id" class="conversation-item" :class="{ selected: current?.id === item.id }" @click="open(item.id)"><span class="avatar">{{ item.contact.display_name?.slice(0, 1) || '?' }}</span><div class="conversation-copy"><div><strong>{{ item.contact.display_name }}</strong><time>{{ dateTime(item.updated_at) }}</time></div><p>{{ item.preview || '尚無訊息' }}</p><div class="conversation-meta"><span v-if="item.sandbox" class="plain-label">本地演練</span><span v-else-if="item.contact.tags?.length" class="location-label"><Icon name="pin" :size="12" />{{ item.contact.tags[0] }}</span><span v-if="item.unread_count" class="count-badge mini">{{ item.unread_count }}</span></div></div></button><EmptyState v-if="!loading && !items.length" title="目前沒有對話" description="連接通道後，客戶訊息會出現在這裡。" /></div><div v-if="user.role === 'admin'" class="list-footer"><button class="btn subtle full" :disabled="busy" @click="sandbox"><Icon name="plus" :size="17" />建立本地演練</button><small>僅在本機，訊息不會傳送至 WhatsApp</small></div></section>
    <section v-if="!current" class="conversation-welcome"><div class="welcome-orbits"><div class="welcome-chat"><Icon name="inbox" :size="52" /><span /></div></div><span class="eyebrow">專屬客服工作空間</span><h2>讓每一次對話都有好開始</h2><p>從左側選擇一段對話，查看訊息與客戶資料。<br />也可以建立本地演練，熟悉客服工作流程。</p><div class="welcome-features"><span><Icon name="users" :size="16" />共享收件匣</span><span><Icon name="sparkles" :size="16" />AI 建議回覆</span><span><Icon name="shield" :size="16" />人工掌控</span></div><div v-if="error" class="alert error" role="alert">{{ error }}</div></section>
    <template v-else><section class="chat-pane"><header class="chat-heading"><button class="icon-btn mobile-back" aria-label="返回會話列表" @click="current = null"><Icon name="chevron" /></button><span class="avatar">{{ current.contact.display_name?.slice(0, 1) }}</span><div><h2>{{ current.contact.display_name }}</h2><p>{{ current.sandbox ? '本地演練 · 不會外發' : 'WhatsApp 對話' }}<span class="divider-dot">·</span>{{ statusLabel(current.mode) }}</p></div><button class="btn" :disabled="busy || current.mode === 'manual'" @click="change({ mode: 'manual' })"><Icon name="users" :size="17" />{{ current.mode === 'manual' ? '人工接待中' : '人工接管' }}</button></header><div v-if="error" class="alert error inline-alert" role="alert">{{ error }}</div><div v-if="current.sandbox" class="sandbox-banner"><Icon name="info" :size="15" />本地演練會話，訊息與回執不代表真實 WhatsApp 同步。</div><div ref="messageArea" class="message-area"><div class="conversation-day">{{ dateTime(current.updated_at) }}</div><div v-for="message in current.messages" :key="message.id" class="message" :class="message.direction"><div class="message-bubble"><span v-if="message.direction === 'internal'" class="message-note-label"><Icon name="lock" :size="12" />內部備註 · 僅客服可見</span><p>{{ message.body || `［${messageKindLabel(message.kind)} 訊息］` }}</p><span v-if="message.kind !== 'text' && message.kind !== 'note'" class="muted small-text">附件類型：{{ messageKindLabel(message.kind) }} · 媒體預覽待聯調</span></div><div class="message-meta">{{ dateTime(message.created_at) }}<span v-if="message.direction === 'outgoing'">{{ statusLabel(message.status) }}</span><Icon v-if="message.status === 'read'" name="doublecheck" :size="15" /></div></div><EmptyState v-if="!current.messages?.length" title="對話已準備好" description="新增內部備註，或在演練會話中模擬客戶訊息。" icon="inbox" /></div><div class="chat-compose"><div v-if="suggestion" class="suggestion-card"><div><strong><Icon name="sparkles" :size="16" />AI 建議回覆</strong><span class="badge">{{ statusLabel(suggestion.status) }}</span></div><p>{{ suggestion.answer }}</p><small>{{ suggestion.citations.length }} 個來源 · {{ statusLabel(suggestion.retrieval_mode) }}</small><button v-if="suggestion.answer" class="btn small" @click="text = suggestion.answer; replyType = 'reply'">放入輸入框</button></div><form v-if="current.sandbox" class="simulate-row" @submit.prevent="simulate"><Icon name="users" :size="16" /><input v-model="simulatedText" aria-label="模擬客戶訊息" placeholder="模擬客戶說了什麼…" /><button class="btn small" :disabled="busy || !simulatedText.trim()">模擬收到</button></form><form class="composer" :class="{ 'note-composer': replyType === 'note' }" @submit.prevent="send"><div class="composer-tabs"><button type="button" :class="{ active: replyType === 'reply' }" @click="replyType = 'reply'">回覆</button><button type="button" :class="{ active: replyType === 'note' }" @click="replyType = 'note'"><Icon name="lock" :size="13" />內部備註</button><button type="button" class="ai-compose" :disabled="busy" @click="suggest"><Icon name="sparkles" :size="16" />AI 建議</button></div><textarea v-model="text" :placeholder="replyType === 'note' ? '寫下內部備註，只有客服可見…' : '輸入訊息…'" aria-label="訊息內容" rows="3" @keydown.ctrl.enter.prevent="send" /><div class="composer-bottom"><span>{{ replyType === 'note' ? '內部備註不會外發' : current.sandbox ? '僅儲存至本地演練' : '真實外發依伺服器授權控制' }}</span><button class="btn primary" :disabled="busy || !text.trim()"><Icon name="send" :size="16" />{{ replyType === 'note' ? '儲存備註' : '傳送' }}</button></div></form></div></section><aside class="customer-panel"><div class="panel-title"><h3>客戶資料</h3><Icon name="users" :size="17" /></div><div class="customer-profile"><span class="avatar large">{{ current.contact.display_name?.slice(0, 1) }}</span><h3>{{ current.contact.display_name }}</h3><p>{{ current.contact.phone || '未設定電話' }}</p><div class="tags"><span v-for="tag in current.contact.tags" :key="tag" class="tag-neutral">{{ tag }}</span></div></div><div class="customer-fields"><label>負責客服<select v-model="selectedUser" :disabled="busy"><option value="">未分配</option><option v-for="agent in users" :key="agent.id" :value="agent.id">{{ agent.display_name }}</option></select></label><label>接待模式<select :value="current.mode" :disabled="busy" @change="change({ mode: ($event.target as HTMLSelectElement).value })"><option value="manual">人工接待</option><option value="ai_draft">AI 建議回覆</option></select></label><div><span class="field-caption">語言</span><p>{{ languageLabel(current.contact.language) }}</p></div><div v-for="(value, key) in current.contact.attributes" :key="key"><span class="field-caption">{{ key }}</span><p>{{ value }}</p></div><div><span class="field-caption">客戶備註</span><p class="customer-note">{{ current.contact.notes || '尚未新增備註' }}</p></div></div><div class="customer-privacy"><Icon name="shield" :size="16" /><p>客戶資料僅用於服務。<br />AI 建議經客服確認後再傳送。</p></div></aside></template>
  </div>
</template>
