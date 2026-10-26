<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, dateTime, errorMessage, safeLink, statusLabel } from '../api'
import type { Product, User } from '../types'
import Icon from '../components/Icon.vue'
import EmptyState from '../components/EmptyState.vue'

const props = defineProps<{ user: User }>()
const canEdit = computed(() => ['admin', 'knowledge_manager'].includes(props.user.role))
const items = ref<Product[]>([])
const query = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const toast = ref('')
const editing = ref<Product | null>(null)
const confirmed = ref(false)
const form = ref({ name: '', sku: '', country: '', card_type: '', days: '', data_allowance: '', price: '', original_price: '', currency: '', url: '' })
function money(product: Product) { return product.price === null || product.price === '' ? '待核實' : `${product.currency || '未標明幣種'} ${Number(product.price).toLocaleString('en-HK', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` }
async function load() {
  loading.value = true
  try { items.value = await api<Product[]>(`/products?q=${encodeURIComponent(query.value)}`) }
  catch (err) { error.value = errorMessage(err) }
  finally { loading.value = false }
}
function edit(product: Product) {
  editing.value = product; error.value = ''; confirmed.value = false
  form.value = { name: product.name, sku: product.sku ?? '', country: product.country ?? '', card_type: product.card_type ?? '', days: product.days?.toString() ?? '', data_allowance: product.data_allowance ?? '', price: product.price?.toString() ?? '', original_price: product.original_price?.toString() ?? '', currency: product.currency ?? '', url: product.url ?? '' }
}
async function save(publish = false) {
  if (!editing.value) return
  busy.value = true; error.value = ''
  try {
    const payload = Object.fromEntries(Object.entries(form.value).filter(([key]) => key !== 'url').map(([key, value]) => [key, value === '' ? null : ['price', 'original_price', 'days'].includes(key) ? Number(value) : value]))
    await api(`/products/${editing.value.id}`, 'PATCH', payload)
    if (publish) await api(`/products/${editing.value.id}/publish`, 'POST')
    toast.value = publish ? '商品已核實發布。' : '商品資料已儲存，請審核後發布。'
    editing.value = null; await load()
  } catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
onMounted(load)
</script>

<template>
  <div class="page-content"><div class="info-banner"><Icon name="shield" :size="22" /><div><strong>價格與套餐，以已核實資料為準</strong><p>商品由網站採集識別。未知欄位保留空白，AI 不會自行補出價格。</p></div></div><div class="toolbar"><form class="search-field" @submit.prevent="load"><Icon name="search" :size="18" /><input v-model="query" aria-label="搜尋商品" placeholder="搜尋商品、目的地或商品編號…" /><button class="text-btn">搜尋</button></form><span class="muted">{{ items.length }} 項商品</span><button class="btn" @click="load"><Icon name="refresh" :size="16" />重新整理</button></div><div v-if="error && !editing" class="alert error" role="alert">{{ error }}</div><div v-if="toast" class="alert success" role="status">{{ toast }}</div><div class="card table-card"><div v-if="loading" class="loading-line">正在載入商品…</div><table v-if="items.length"><thead><tr><th>商品與套餐</th><th>目的地</th><th>規格</th><th>價格</th><th>狀態</th><th>操作</th></tr></thead><tbody><tr v-for="product in items" :key="product.id"><td><strong class="product-name">{{ product.name }}</strong><small class="muted">{{ product.sku || '未提供商品編號' }}</small></td><td>{{ product.country || '待核實' }}</td><td><div>{{ product.card_type || '類型待核實' }}</div><small class="muted">{{ product.days !== null ? `${product.days} 天` : '天數待核實' }} · {{ product.data_allowance || '流量待核實' }}</small></td><td class="price-cell">{{ money(product) }}</td><td><span class="badge" :class="product.status">{{ statusLabel(product.status) }}</span></td><td><button class="btn small" @click="edit(product)">{{ canEdit ? '審閱資料' : '查看資料' }}<Icon name="chevron" :size="14" /></button></td></tr></tbody></table><EmptyState v-else-if="!loading" title="尚無商品資料" description="先在網站知識庫新增來源並採集，識別出的商品會出現在這裡等待審核。" icon="tag" /></div></div>
  <div v-if="editing" class="modal-backdrop" @click.self="!busy && (editing = null)"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="product-title"><header><div><span class="eyebrow">商品審核</span><h2 id="product-title">審閱商品資料</h2></div><button class="icon-btn" aria-label="關閉" :disabled="busy" @click="editing = null"><Icon name="close" /></button></header><form @submit.prevent="save(false)"><div class="modal-body"><div v-if="error" class="alert error" role="alert">{{ error }}</div><div class="editor-status"><span class="badge" :class="editing.status">{{ statusLabel(editing.status) }}</span><small class="muted">核實時間：{{ dateTime(editing.verified_at) }}</small></div><label>商品名稱<input v-model="form.name" required :readonly="!canEdit" /></label><div class="form-grid"><label>商品編號<input v-model="form.sku" :readonly="!canEdit" placeholder="未知可留空" /></label><label>目的地<input v-model="form.country" :readonly="!canEdit" placeholder="未知可留空" /></label><label>卡類型<select v-model="form.card_type" :disabled="!canEdit"><option value="">待核實</option><option value="SIM">實體 SIM</option><option value="eSIM">eSIM</option><option v-if="form.card_type && !['SIM','eSIM'].includes(form.card_type)" :value="form.card_type">{{ form.card_type }}</option></select></label><label>有效天數<input v-model="form.days" :readonly="!canEdit" type="number" min="1" step="1" placeholder="未知可留空" /></label><label>流量<input v-model="form.data_allowance" :readonly="!canEdit" placeholder="依來源填寫" /></label><label>幣種<input v-model="form.currency" :readonly="!canEdit" maxlength="8" placeholder="例如 HKD" /></label><label>現價<input v-model="form.price" :readonly="!canEdit" type="number" min="0" step="0.01" placeholder="未知可留空" /></label><label>原價<input v-model="form.original_price" :readonly="!canEdit" type="number" min="0" step="0.01" placeholder="未知可留空" /></label></div><label>商品來源網址<input v-model="form.url" readonly type="url" /></label><a v-if="safeLink(form.url)" :href="safeLink(form.url)" target="_blank" rel="noopener noreferrer" class="source-link"><Icon name="external" :size="15" />開啟商品來源核對</a><label v-if="canEdit" class="checkbox-label"><input v-model="confirmed" type="checkbox" />我已根據來源核對本次資料，確認可提供給客服使用。</label></div><footer><button type="button" class="btn" :disabled="busy" @click="editing = null">關閉</button><div class="footer-spacer" /><button v-if="canEdit" class="btn" :disabled="busy">儲存草稿</button><button v-if="canEdit" type="button" class="btn primary" :disabled="busy || !confirmed || !form.name.trim()" @click="save(true)">儲存並發布</button></footer></form></section></div>
</template>
