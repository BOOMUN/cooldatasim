<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import { languageLabel } from '../localization'
import type { Contact, Conversation, User } from '../types'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'

defineProps<{ user: User }>()
const emit = defineEmits<{ conversation: [id: number] }>()
const items = ref<Contact[]>([])
const query = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const editor = ref(false)
const editingId = ref<number | null>(null)
const form = ref({ display_name: '', phone: '', language: 'zh-Hant', tags: '', notes: '' })
const attributes = ref<{ key: string; value: string }[]>([])
async function load() {
  loading.value = true; error.value = ''
  try { items.value = await api<Contact[]>(`/contacts?q=${encodeURIComponent(query.value)}`) }
  catch (err) { error.value = errorMessage(err) }
  finally { loading.value = false }
}
function edit(contact?: Contact) {
  editingId.value = contact?.id ?? null
  form.value = { display_name: contact?.display_name ?? '', phone: contact?.phone ?? '', language: contact?.language ?? 'zh-Hant', tags: contact?.tags?.join('，') ?? '', notes: contact?.notes ?? '' }
  attributes.value = Object.entries(contact?.attributes ?? {}).map(([key, value]) => ({ key, value: String(value) }))
  error.value = ''; editor.value = true
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const body = { ...form.value, tags: form.value.tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean), attributes: Object.fromEntries(attributes.value.filter(item => item.key.trim()).map(item => [item.key.trim(), item.value])) }
    await api(editingId.value ? `/contacts/${editingId.value}` : '/contacts', editingId.value ? 'PATCH' : 'POST', body)
    editor.value = false; await load()
  } catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function start(contact: Contact) {
  busy.value = true; error.value = ''
  try { const conversation = await api<Conversation>('/conversations', 'POST', { contact_id: contact.id }); emit('conversation', conversation.id) }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="page-content"><div class="toolbar"><form class="search-field" @submit.prevent="load"><Icon name="search" :size="18" /><input v-model="query" aria-label="搜尋客戶" placeholder="搜尋姓名或電話…" /><button class="text-btn">搜尋</button></form><span class="muted toolbar-count">{{ items.length }} 位客戶</span><button class="btn primary" @click="edit()"><Icon name="plus" :size="17" />新增客戶</button></div><div v-if="error && !editor" class="alert error" role="alert">{{ error }}</div><div class="card table-card"><div v-if="loading" class="loading-line">正在載入客戶資料…</div><table v-if="items.length"><thead><tr><th>客戶</th><th>電話</th><th>標籤</th><th>備註</th><th class="align-right">操作</th></tr></thead><tbody><tr v-for="contact in items" :key="contact.id"><td><div class="person-cell"><span class="avatar small">{{ contact.display_name?.slice(0, 1) }}</span><div><strong>{{ contact.display_name }}</strong><small>{{ languageLabel(contact.language) }}</small></div></div></td><td>{{ contact.phone || '—' }}</td><td><div class="tags"><span v-for="tag in contact.tags" :key="tag" class="tag-neutral">{{ tag }}</span><span v-if="!contact.tags?.length" class="muted">—</span></div></td><td><p class="table-note">{{ contact.notes || '—' }}</p></td><td><div class="row-actions"><button class="btn small" :disabled="busy" @click="start(contact)"><Icon name="inbox" :size="15" />開啟對話</button><button class="icon-btn" :aria-label="`編輯${contact.display_name}`" @click="edit(contact)"><Icon name="edit" :size="17" /></button></div></td></tr></tbody></table><EmptyState v-else-if="!loading" title="建立你的第一位客戶" description="集中管理客戶資料、標籤與服務備註。" icon="users"><button class="btn" @click="edit()"><Icon name="plus" :size="17" />新增客戶</button></EmptyState></div></div>
  <div v-if="editor" class="modal-backdrop" @click.self="!busy && (editor = false)"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="contact-title"><header><div><span class="eyebrow">客戶檔案</span><h2 id="contact-title">{{ editingId ? '編輯客戶資料' : '新增客戶' }}</h2></div><button class="icon-btn" aria-label="關閉" :disabled="busy" @click="editor = false"><Icon name="close" /></button></header><form @submit.prevent="save"><div class="modal-body"><div v-if="error" class="alert error" role="alert">{{ error }}</div><div class="form-grid"><label>客戶名稱<input v-model="form.display_name" required maxlength="160" placeholder="輸入姓名" /></label><label>電話號碼<input v-model="form.phone" type="tel" required minlength="3" maxlength="80" placeholder="例如 +852…" /></label><label>語言<select v-model="form.language"><option value="zh-Hant">繁體中文</option><option value="zh-Hans">簡體中文</option><option value="en">英語</option></select></label><label>標籤<input v-model="form.tags" placeholder="以逗號分隔，例如 日本，新客戶" /></label></div><label>客戶備註<textarea v-model="form.notes" rows="4" maxlength="5000" placeholder="記錄偏好與服務注意事項…" /></label><div class="section-label"><strong>自訂欄位</strong><button type="button" class="text-btn" @click="attributes.push({ key: '', value: '' })">+ 新增欄位</button></div><div v-for="(attr, index) in attributes" :key="index" class="attribute-row"><input v-model="attr.key" aria-label="欄位名稱" placeholder="欄位名稱" /><input v-model="attr.value" aria-label="欄位內容" placeholder="內容" /><button type="button" class="icon-btn" aria-label="移除欄位" @click="attributes.splice(index, 1)"><Icon name="close" :size="16" /></button></div><p class="muted small-text">例如：公司、電郵、旅遊目的地。資料只儲存在本項目。</p></div><footer><button type="button" class="btn" :disabled="busy" @click="editor = false">取消</button><button class="btn primary" :disabled="busy">{{ busy ? '儲存中…' : '儲存資料' }}</button></footer></form></section></div>
</template>
