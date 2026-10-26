<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, clearSession, errorMessage, setCsrf } from './api'
import type { Auth, User } from './types'
import Icon from './components/Icon.vue'
import Inbox from './views/Inbox.vue'
import Contacts from './views/Contacts.vue'
import Knowledge from './views/Knowledge.vue'
import Products from './views/Products.vue'
import Intelligence from './views/Intelligence.vue'
import Settings from './views/Settings.vue'

const user = ref<User | null>(null)
const checking = ref(true)
const busy = ref(false)
const error = ref('')
const username = ref('')
const password = ref('')
const page = ref('inbox')
const mobileNav = ref(false)
const conversationId = ref<number | null>(null)
const nav = [
  { id: 'inbox', icon: 'inbox', label: '收件匣', caption: '與每位客戶保持連繫' },
  { id: 'contacts', icon: 'users', label: '客戶資料', caption: '讓每次服務更了解客戶' },
  { id: 'knowledge', icon: 'book', label: '網站知識庫', caption: '有依據的知識，安心的回答' },
  { id: 'products', icon: 'tag', label: '商品資料', caption: '讓套餐與價格有據可查' },
  { id: 'intelligence', icon: 'sparkles', label: 'AI 測試台', caption: '檢索、理解，再回答' },
  { id: 'whatsapp', icon: 'phone', label: 'WhatsApp 連線', caption: '訊息通道與同步狀態' },
  { id: 'settings', icon: 'settings', label: '系統設定', caption: '服務與模型連線狀態' },
]
const active = computed(() => nav.find(item => item.id === page.value)!)
const roleLabel = computed(() => ({ admin: '管理員', knowledge_manager: '知識管理員', agent: '客服人員' }[user.value?.role ?? ''] ?? '客服人員'))
function expire() { user.value = null; password.value = ''; clearSession(); error.value = '登入已過期，請重新登入。' }
async function restore() {
  try { const session = await api<Auth>('/auth/me'); user.value = session.user; setCsrf(session.csrf_token) }
  catch (err) { if (!(err instanceof Error) || !('status' in err) || err.status !== 401) error.value = errorMessage(err) }
  finally { checking.value = false }
}
async function login() {
  busy.value = true; error.value = ''
  try { const session = await api<Auth>('/auth/login', 'POST', { username: username.value, password: password.value }); setCsrf(session.csrf_token); user.value = session.user; password.value = '' }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
async function logout() {
  busy.value = true
  try { await api('/auth/logout', 'POST'); clearSession(); user.value = null; error.value = ''; page.value = 'inbox'; conversationId.value = null }
  catch (err) { error.value = errorMessage(err) }
  finally { busy.value = false }
}
function navigate(id: string) { page.value = id; mobileNav.value = false; error.value = '' }
function openConversation(id: number) { conversationId.value = id; navigate('inbox') }
onMounted(() => { void restore(); window.addEventListener('session-expired', expire) })
onBeforeUnmount(() => window.removeEventListener('session-expired', expire))
</script>

<template>
  <div v-if="checking" class="boot"><img src="/logo.png" alt="Cool Data Sim" /><span class="spinner" /><p>正在連接工作台…</p></div>
  <main v-else-if="!user" class="login-page">
    <section class="login-story"><img src="/logo.png" alt="Cool Data Sim" /><div><span class="eyebrow">Cool Data Sim · 專屬客服</span><h1>每一次連繫，<br />都值得用心回應。</h1><p>將客戶對話、網站知識與 AI 助手，<br />放在同一個工作台。</p><div class="story-line"><span /><span /><span /></div></div><p class="login-foot">客服工作台 <span>本機工作區</span></p></section>
    <section class="login-form-wrap"><form class="login-form" @submit.prevent="login"><div class="login-symbol"><Icon name="shield" :size="28" /></div><span class="eyebrow">歡迎回來</span><h2>登入客服工作台</h2><p class="muted">使用本機管理員建立的帳號繼續。</p><div v-if="error" class="alert error" role="alert">{{ error }}</div><label>帳號<input v-model="username" autocomplete="username" required autofocus placeholder="輸入你的帳號" /></label><label>密碼<input v-model="password" type="password" autocomplete="current-password" required placeholder="輸入密碼" /></label><button class="btn primary login-submit" :disabled="busy">{{ busy ? '正在登入…' : '登入工作台' }}<Icon name="arrow" /></button><div class="login-note"><Icon name="lock" :size="15" />登入資料僅用於本機工作台</div></form></section>
  </main>
  <div v-else class="app-shell">
    <header class="topbar"><button class="icon-btn mobile-menu" aria-label="開啟導航" @click="mobileNav = !mobileNav"><Icon name="menu" /></button><a href="#" class="brand" @click.prevent="navigate('inbox')"><img src="/logo.png" alt="Cool Data Sim" /></a><div class="workspace-title">客服工作台<span>客戶服務</span></div><div class="topbar-spacer" /><span class="workspace-label"><span class="dot teal" />本機工作區</span><div class="topbar-user"><span class="avatar small">{{ user.display_name?.slice(0, 1) || 'C' }}</span><div><strong>{{ user.display_name || user.username }}</strong><small>{{ roleLabel }}</small></div><button class="icon-btn" aria-label="登出" title="登出" :disabled="busy" @click="logout"><Icon name="logout" :size="18" /></button></div></header>
    <aside class="sidebar" :class="{ open: mobileNav }"><div class="nav-caption">工作空間</div><nav><button v-for="item in nav" :key="item.id" class="nav-item" :class="{ active: page === item.id }" @click="navigate(item.id)"><Icon :name="item.icon" :size="22" /><span>{{ item.label }}</span><span v-if="page === item.id" class="nav-mark" /></button></nav><div class="sidebar-bottom"><div class="workspace-monogram">C</div><div><strong>Cool Data Sim</strong><small>專屬客服工作區</small></div><Icon name="lock" :size="15" /></div></aside>
    <div v-if="mobileNav" class="nav-scrim" @click="mobileNav = false" />
    <main class="main-workspace"><div v-if="error" class="alert error global-error" role="alert">{{ error }}<button class="icon-btn" aria-label="關閉" @click="error = ''"><Icon name="close" :size="16" /></button></div><Inbox v-if="page === 'inbox'" :user="user" :initial-id="conversationId" /><template v-else><div class="page-heading"><div><span class="eyebrow">{{ page === 'intelligence' ? 'AI 工作區' : '客戶服務' }}</span><h1>{{ active.label }}</h1><p>{{ active.caption }}</p></div><div class="heading-decor"><Icon :name="active.icon" :size="32" /></div></div><Contacts v-if="page === 'contacts'" :user="user" @conversation="openConversation" /><Knowledge v-else-if="page === 'knowledge'" :user="user" /><Products v-else-if="page === 'products'" :user="user" /><Intelligence v-else-if="page === 'intelligence'" /><Settings v-else :kind="page" :user="user" :key="page" /></template></main>
  </div>
</template>
