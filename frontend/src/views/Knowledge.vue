<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, dateTime, errorMessage, safeLink, statusLabel } from '../api'
import { categoryLabel } from '../localization'
import { hasPublishedSnapshot as documentHasPublishedSnapshot, jobScopeSummary, jobStatusLabel } from '../knowledgePresentation'
import type { Document, Job, Source, User } from '../types'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps<{ user: User }>()
const canEdit = computed(() => ['admin', 'knowledge_manager'].includes(props.user.role))
const tab = ref('documents')
const documents = ref<Document[]>([])
const sources = ref<Source[]>([])
const jobs = ref<Job[]>([])
const query = ref('')
const status = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const toast = ref('')
const sourceDialog = ref(false)
const sourceForm = ref({ name: '', url: 'https://www.cooldatasim.com/', max_pages: 10 })
const editor = ref(false)
const editingId = ref<number | null>(null)
const documentStatus = ref('draft')
const documentRevision = ref(1)
const hasPublishedSnapshot = ref(false)
const form = ref({ title: '', url: '', category: 'general', content: '' })
const savedForm = ref('')
const hasUnsavedChanges = computed(() => JSON.stringify(form.value) !== savedForm.value)
const confirmPublish = ref(false)
const publishedCount = computed(() => documents.value.filter(documentHasPublishedSnapshot).length)
let poll: ReturnType<typeof setInterval> | undefined

async function load(quiet = false) {
  if (!quiet) loading.value = true
  const results = await Promise.allSettled([
    api<Document[]>(`/documents?q=${encodeURIComponent(query.value)}&status=${status.value}`),
    api<Source[]>('/sources'), api<Job[]>('/jobs'),
  ])
  if (results[0].status === 'fulfilled') documents.value = results[0].value
  if (results[1].status === 'fulfilled') sources.value = results[1].value
  if (results[2].status === 'fulfilled') jobs.value = results[2].value
  const failures = results.filter(result => result.status === 'rejected')
  error.value = failures.map(result => errorMessage((result as PromiseRejectedResult).reason)).join('；')
  loading.value = false
}
async function addSource() {
  busy.value = true; error.value = ''
  try { await api('/sources', 'POST', sourceForm.value); sourceDialog.value = false; sourceForm.value = { name: '', url: 'https://www.cooldatasim.com/', max_pages: 10 }; toast.value = '網站來源已新增，可以開始採集。'; await load() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function sync(source: Source) {
  busy.value = true; error.value = ''
  try { await api(`/sources/${source.id}/sync`, 'POST'); toast.value = '採集任務已提交。新內容會保留為待審核草稿。'; tab.value = 'jobs'; await load() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function edit(document?: Document) {
  busy.value = true; error.value = ''; confirmPublish.value = false
  try {
    const detail = document ? await api<Document>(`/documents/${document.id}`) : null
    editingId.value = detail?.id ?? null; documentStatus.value = detail?.status ?? 'draft'; documentRevision.value = detail?.revision ?? 1
    hasPublishedSnapshot.value = detail ? documentHasPublishedSnapshot(detail) : false
    form.value = { title: detail?.title ?? '', url: detail?.url ?? '', category: detail?.category ?? 'general', content: detail?.content ?? '' }
    savedForm.value = JSON.stringify(form.value)
    editor.value = true
  } catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''
  try { const result = await api<Document>(editingId.value ? `/documents/${editingId.value}` : '/documents', editingId.value ? 'PATCH' : 'POST', form.value); editingId.value = result.id; documentStatus.value = result.status; documentRevision.value = result.revision; confirmPublish.value = false; toast.value = '內容已儲存，發布前請核對來源與資料。'; editor.value = false; await load() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function publish() {
  if (!editingId.value || hasUnsavedChanges.value) return
  busy.value = true; error.value = ''
  try { await api(`/documents/${editingId.value}/publish`, 'POST'); toast.value = '已發布目前儲存的版本，可用於客服檢索。'; editor.value = false; confirmPublish.value = false; await load() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function withdraw() {
  if (!editingId.value) return
  busy.value = true; error.value = ''
  try { await api(`/documents/${editingId.value}/withdraw`, 'POST'); toast.value = '知識已撤回，停止用於新的客服檢索。'; editor.value = false; await load() }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
onMounted(() => { void load(); poll = setInterval(() => { if (jobs.value.some(job => ['pending', 'running', 'queued'].includes(job.status)) && !editor.value && !sourceDialog.value) void load(true) }, 4000) })
onBeforeUnmount(() => clearInterval(poll))
</script>

<template>
  <div class="page-content"><div class="knowledge-summary"><div class="summary-note"><div class="summary-icon"><Icon name="book" :size="25" /></div><div><h3>讓回答從可信資料開始</h3><p>採集內容先進入草稿，審核發布後才會提供給 AI。</p></div></div><div class="summary-number"><strong>{{ sources.length }}</strong><span>網站來源</span></div><div class="summary-number"><strong>{{ documents.length }}</strong><span>目前文檔</span></div><div class="summary-number"><strong>{{ publishedCount }}</strong><span>生效版本</span></div></div><div class="section-tabs"><button :class="{ active: tab === 'documents' }" @click="tab = 'documents'"><Icon name="file" :size="17" />知識文檔</button><button :class="{ active: tab === 'sources' }" @click="tab = 'sources'"><Icon name="globe" :size="17" />網站來源</button><button :class="{ active: tab === 'jobs' }" @click="tab = 'jobs'"><Icon name="clock" :size="17" />採集紀錄</button></div><div v-if="error && !editor && !sourceDialog" class="alert error" role="alert">{{ error }}</div><div v-if="toast" class="alert success" role="status">{{ toast }}<button class="icon-btn" aria-label="關閉提示" @click="toast = ''"><Icon name="close" :size="15" /></button></div>
    <template v-if="tab === 'documents'"><div class="toolbar"><form class="search-field" @submit.prevent="load()"><Icon name="search" :size="18" /><input v-model="query" aria-label="搜尋知識" placeholder="搜尋標題或內容…" /><button class="text-btn">搜尋</button></form><select v-model="status" aria-label="篩選狀態" @change="load()"><option value="">所有狀態</option><option value="draft">待審核</option><option value="published">已發布</option><option value="withdrawn">已撤回</option></select><button v-if="canEdit" class="btn primary" @click="edit()"><Icon name="plus" :size="17" />新增文檔</button></div><div class="card table-card"><div v-if="loading" class="loading-line">正在載入知識文檔…</div><table v-if="documents.length"><thead><tr><th>文檔與來源</th><th>分類</th><th>發布狀態</th><th>向量狀態</th><th>更新時間</th><th /></tr></thead><tbody><tr v-for="document in documents" :key="document.id" class="clickable-row" @click="edit(document)"><td><div class="document-cell"><span class="file-icon"><Icon name="file" :size="19" /></span><div><strong>{{ document.title }}</strong><small>{{ document.url || '手動建立' }}</small></div></div></td><td>{{ categoryLabel(document.category) }}</td><td><span class="badge" :class="document.status">{{ statusLabel(document.status) }}</span><small v-if="document.status === 'draft' && documentHasPublishedSnapshot(document)" class="muted">待審修訂 · 舊版仍生效</small></td><td><span class="muted small-text">{{ statusLabel(document.vector_status || 'not_configured') }}</span></td><td class="nowrap muted">{{ dateTime(document.updated_at) }}</td><td><button class="icon-btn" :aria-label="`查看${document.title}`" @click.stop="edit(document)"><Icon name="chevron" :size="17" /></button></td></tr></tbody></table><EmptyState v-else-if="!loading" title="知識庫從一個來源開始" description="新增網站來源採集內容，或手動撰寫客服知識。" icon="book"><button v-if="canEdit" class="btn" @click="tab = 'sources'; sourceDialog = true"><Icon name="plus" :size="17" />新增網站來源</button></EmptyState></div></template>
    <template v-else-if="tab === 'sources'"><div class="toolbar"><div class="muted">只採集允許範圍內的公開網站內容。</div><button v-if="canEdit" class="btn primary" @click="sourceDialog = true; error = ''"><Icon name="plus" :size="17" />新增網站來源</button></div><div class="source-grid"><article v-for="source in sources" :key="source.id" class="card source-card"><div class="source-top"><span class="source-icon"><Icon name="globe" :size="24" /></span><span class="badge">{{ statusLabel(source.status) }}</span></div><h3>{{ source.name }}</h3><a :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.url }}<Icon name="external" :size="13" /></a><dl><div><dt>採集上限</dt><dd>{{ source.max_pages }} 頁</dd></div><div><dt>最近同步</dt><dd>{{ dateTime(source.last_synced) }}</dd></div></dl><button v-if="canEdit" class="btn full" :disabled="busy" @click="sync(source)"><Icon name="refresh" :size="16" />採集為草稿</button></article></div><EmptyState v-if="!sources.length && !loading" title="尚未加入網站" description="先設定網站網址和每次採集頁數。" icon="globe" /></template>
    <template v-else><div class="toolbar"><span class="muted">每次依頁數上限採集；本批次完成不代表全站已採集，也不代表知識已發布。</span><button class="btn" @click="load()"><Icon name="refresh" :size="16" />重新整理</button></div><div class="card table-card"><table v-if="jobs.length"><thead><tr><th>任務</th><th>網站來源</th><th>狀態</th><th>本批次進度</th><th>建立時間</th></tr></thead><tbody><template v-for="job in jobs" :key="job.id"><tr><td><strong>#{{ job.id }}</strong></td><td>{{ sources.find(source => source.id === job.source_id)?.name || `來源 #${job.source_id}` }}</td><td><span class="badge" :class="job.result?.limit_reached ? 'limited' : job.status">{{ jobStatusLabel(job) }}</span></td><td>{{ job.progress ?? 0 }}%</td><td>{{ dateTime(job.created_at) }}</td></tr><tr><td colspan="5" class="job-scope" :class="{ limited: job.result?.limit_reached }">{{ jobScopeSummary(job) }}</td></tr><tr v-if="job.error"><td colspan="5" class="job-error">{{ job.error }}</td></tr></template></tbody></table><EmptyState v-else title="尚無採集紀錄" description="從網站來源啟動採集後，可以在這裡追蹤結果。" icon="clock" /></div></template>
  </div>
  <div v-if="sourceDialog" class="modal-backdrop" @click.self="!busy && (sourceDialog = false)"><section class="modal compact" role="dialog" aria-modal="true" aria-labelledby="source-title"><header><h2 id="source-title">新增網站來源</h2><button class="icon-btn" aria-label="關閉" :disabled="busy" @click="sourceDialog = false"><Icon name="close" /></button></header><form @submit.prevent="addSource"><div class="modal-body"><div v-if="error" class="alert error" role="alert">{{ error }}</div><label>來源名稱<input v-model="sourceForm.name" required maxlength="160" placeholder="例如 Cool Data Sim 官方網站" /></label><label>網站網址<input v-model="sourceForm.url" type="url" required placeholder="https://www.cooldatasim.com/" /></label><label>每次最多採集頁數<input v-model.number="sourceForm.max_pages" type="number" min="1" max="50" required /></label><p class="muted small-text">新增來源後，按「採集為草稿」開始。系統不會自動發布內容。</p></div><footer><button type="button" class="btn" :disabled="busy" @click="sourceDialog = false">取消</button><button class="btn primary" :disabled="busy">新增來源</button></footer></form></section></div>
  <div v-if="editor" class="modal-backdrop" @click.self="!busy && (editor = false)"><section class="modal wide" role="dialog" aria-modal="true" aria-labelledby="document-title"><header><div><span class="eyebrow">知識審核 · 版本 {{ documentRevision }}</span><h2 id="document-title">{{ editingId ? '審閱知識文檔' : '新增知識文檔' }}</h2></div><button class="icon-btn" aria-label="關閉" :disabled="busy" @click="editor = false"><Icon name="close" /></button></header><form @submit.prevent="save"><div class="modal-body"><div v-if="error" class="alert error" role="alert">{{ error }}</div><div class="editor-status"><span class="badge" :class="documentStatus">{{ statusLabel(documentStatus) }}</span><span class="muted small-text">修改後請先儲存，再重新開啟審核發布。</span></div><div v-if="documentStatus === 'draft' && hasPublishedSnapshot" class="snapshot-notice" role="status"><Icon name="info" :size="17" /><span>待審修訂，AI 仍使用上次已發布版本。若舊資料已不適用，請先撤回已發布知識。</span></div><label>標題<input v-model="form.title" :readonly="!canEdit" required maxlength="300" minlength="2" /></label><div class="form-grid"><label>來源網址<input v-model="form.url" :readonly="!canEdit" type="url" placeholder="https://…" /></label><label>分類<select v-model="form.category" :disabled="!canEdit"><option value="general">一般知識</option><option value="product">商品與套餐</option><option value="activation">啟用與使用</option><option value="delivery">取卡與配送</option><option value="support">售後與常見問題</option><option v-if="!['general','product','activation','delivery','support'].includes(form.category)" :value="form.category">{{ form.category }}</option></select></label></div><label>知識內容<textarea v-model="form.content" :readonly="!canEdit" required minlength="10" maxlength="100000" rows="14" class="content-editor" placeholder="輸入可核對來源的客服知識…" /></label><div v-if="confirmPublish" class="publish-confirm"><Icon name="info" :size="20" /><div><strong>確認發布目前已儲存的版本？</strong><p>發布後內容會用於 AI 客服回答。請先核對來源、價格與服務條件；未儲存的修改不會包含在本次發布。</p><button type="button" class="btn primary small" :disabled="busy || hasUnsavedChanges" @click="publish">確認發布已儲存版本</button><button type="button" class="text-btn" @click="confirmPublish = false">取消</button></div></div></div><footer><button v-if="canEdit && hasPublishedSnapshot" type="button" class="btn danger-text" :disabled="busy" @click="withdraw">撤回已發布知識</button><div class="footer-spacer" /><button v-if="canEdit && editingId && documentStatus !== 'published'" type="button" class="btn" :disabled="busy || hasUnsavedChanges" @click="confirmPublish = true">審核發布</button><button v-if="canEdit" class="btn primary" :disabled="busy">{{ busy ? '處理中…' : '儲存內容' }}</button><button v-else type="button" class="btn" @click="editor = false">關閉</button></footer></form></section></div>
</template>
