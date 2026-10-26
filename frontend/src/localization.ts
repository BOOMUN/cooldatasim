import { providerLabel, reasoningEffortLabel } from './modelPresentation.ts'

export const STATUS_LABELS: Record<string, string> = {
  draft: '待審核', published: '已發布', withdrawn: '已撤回', pending: '等待中', queued: '排隊中',
  running: '處理中', completed: '已完成', succeeded: '已完成', failed: '失敗', error: '失敗',
  ready: '就緒', ok: '正常', not_configured: '尚未設定', unavailable: '不可用', stale: '待更新',
  manual: '人工接待', ai_draft: 'AI 建議', sending: '傳送中', sent: '已傳送', delivered: '已送達',
  read: '已讀', played: '已播放', received: '已接收', sandbox: '本地演練', internal: '內部備註',
  note: '內部備註', simulated: '本地演練', disabled: '未啟用', needs_human: '需要人工處理',
  lexical_only: '關鍵字檢索', keyword: '關鍵字檢索', keyword_no_vectors: '關鍵字檢索（無可用向量）',
  hybrid: '混合檢索', indexed: '已建立索引', not_indexed: '未建立索引', text_only: '僅文字索引', partial: '部分採集',
  limited: '達採集上限', syncing: '採集中', synced: '本批次已同步', new: '尚未採集', idle: '待命',
  configured: '已設定', open: '已開啟', close: '已關閉', closed: '已關閉', connecting: '連接中',
  connected: '已連接', disconnected: '已中斷', unknown: '未知狀態', listed: '模型清單可見',
  model_not_listed: '模型不在清單中', disabled_pending_validation: '外發已停用，等待驗證',
  implemented_unverified: '已實作，尚未驗證', metadata_only: '僅接收附件資料', not_implemented: '尚未實作',
  unsupported: '暫不支援', instance_mismatch: '實例不符', bounded: '有限批次', timeout: '連接逾時',
}

export function statusLabel(value?: string | null): string {
  return value ? STATUS_LABELS[value] ?? '未識別狀態' : '尚未記錄'
}

export function languageLabel(value?: string | null): string {
  return value ? ({ 'zh-Hant': '繁體中文', 'zh-HK': '繁體中文（香港）', 'zh-TW': '繁體中文（台灣）', 'zh-Hans': '簡體中文', 'zh-CN': '簡體中文', en: '英語', ja: '日語', ko: '韓語' } as Record<string, string>)[value] ?? '其他語言' : '尚未設定'
}

export function categoryLabel(value?: string | null): string {
  return value ? ({ general: '一般知識', product: '商品與套餐', activation: '啟用與使用', delivery: '取卡與配送', support: '售後與常見問題' } as Record<string, string>)[value] ?? value : '一般知識'
}

export function messageKindLabel(value: string): string {
  return ({ text: '文字', note: '內部備註', image: '圖片', video: '影片', audio: '語音', document: '文件', file: '檔案', sticker: '貼圖', location: '位置', contact: '聯絡人', reaction: '表情回應', unsupported: '暫不支援的類型' } as Record<string, string>)[value] ?? '未識別類型'
}

const DIAGNOSTIC_LABELS: Record<string, string> = {
  database: '資料庫', app_version: '應用程式版本', application: '應用程式', schema_version: '資料結構版本',
  delivery: '對外傳送', documents: '知識文檔數', products: '商品數', jobs_pending: '待處理採集任務',
  chat: '對話模型', qwen: '對話模型', embedding: '向量模型', reranker: '重排模型', whatsapp: 'WhatsApp 通道',
  provider: '接入服務', configured: '已設定', enabled: '已啟用', instance: '實例名稱', state: '連線狀態',
  verified: '已驗證同步', status_checked: '已讀取狀態', capabilities: '功能能力', reachable: '服務可連接',
  model: '模型名稱', status: '狀態', inference_verified: '已驗證推理', detail: '說明', error: '錯誤說明',
  error_code: '錯誤狀態', dimensions: '向量維度', text_receive: '接收文字', phone_message_sync: '手機訊息同步',
  text_send: '傳送文字', delivery_receipts: '訊息回執', media_receive: '接收媒體', media_download: '下載媒體',
  media_send: '傳送媒體', edit_revoke: '編輯與撤回', history_sync: '歷史記錄同步', quote_reply: '引用回覆',
  reaction_sync: '表情回應同步', read_state_sync: '已讀狀態同步', pairing: '掃碼關聯', groups_calls: '群組與通話',
  reasoning_effort: '推理強度', display_name: '顯示名稱',
}

function diagnosticValue(value: unknown, key: string): string {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value == null || value === '') return '尚未設定'
  if (typeof value === 'number') return String(value)
  if (typeof value === 'string') {
    if (STATUS_LABELS[value]) return STATUS_LABELS[value]
    if (key === 'provider') return providerLabel(value)
    if (key === 'reasoning_effort') return reasoningEffortLabel(value)
    if (['model', 'display_name', 'instance', 'app_version', 'application'].includes(key)) return value
    if (['detail', 'error'].includes(key)) return value
    return '未識別狀態'
  }
  return '未提供可顯示的資料'
}

export function diagnosticRows(record: Record<string, unknown>, prefix = ''): { label: string; value: string }[] {
  return Object.entries(record).filter(([key]) => key !== 'qwen' || !record.chat).flatMap(([key, value]) => {
    const label = [prefix, DIAGNOSTIC_LABELS[key] ?? '其他狀態項目'].filter(Boolean).join(' · ')
    if (value && typeof value === 'object' && !Array.isArray(value)) return diagnosticRows(value as Record<string, unknown>, label)
    return [{ label, value: diagnosticValue(value, key) }]
  })
}

const FIELD_LABELS: Record<string, string> = {
  username: '帳號', password: '密碼', display_name: '名稱', phone: '電話號碼', language: '語言', tags: '標籤',
  notes: '備註', attributes: '自訂欄位', title: '標題', url: '網址', category: '分類', content: '內容',
  name: '名稱', max_pages: '採集頁數上限', question: '問題', body: '訊息內容', role: '角色', price: '現價',
  original_price: '原價', days: '有效天數', currency: '幣種', sku: '商品編號', country: '目的地',
  card_type: '卡類型', data_allowance: '流量', assigned_user_id: '負責客服', mode: '接待模式',
}

export function validationMessage(item: { type?: string; loc?: (string | number)[]; ctx?: Record<string, unknown> }): string {
  const key = [...(item.loc ?? [])].reverse().find(part => typeof part === 'string' && FIELD_LABELS[part])
  const label = typeof key === 'string' ? FIELD_LABELS[key] : '資料欄位'
  const context = item.ctx ?? {}
  const reasons: Record<string, string> = {
    missing: '必須填寫', string_too_short: `至少需要 ${context.min_length ?? '指定數量的'} 個字元`,
    string_too_long: `不可超過 ${context.max_length ?? '指定數量的'} 個字元`,
    greater_than_equal: `必須大於或等於 ${context.ge ?? '指定下限'}`,
    less_than_equal: `必須小於或等於 ${context.le ?? '指定上限'}`,
    int_parsing: '必須是整數', int_type: '必須是整數', float_parsing: '必須是有效數值',
    finite_number: '必須是有限數值', string_type: '必須是文字', url_parsing: '網址格式不正確',
    too_long: '項目數超過上限', too_short: '項目數不足', value_error: '格式不符合要求',
  }
  return `${label}：${reasons[item.type ?? ''] ?? '格式不符合要求，請檢查輸入內容'}`
}

export function serverErrorMessage(detail: unknown, status: number): string {
  if (Array.isArray(detail)) return detail.map(validationMessage).join('；')
  const standard: Record<string, string> = { 'Not Found': '找不到要求的資料', 'Internal Server Error': '服務暫時發生錯誤，請稍後重試', Forbidden: '沒有操作權限', Unauthorized: '請重新登入', 'Method Not Allowed': '此操作暫不支援', 'Bad Request': '請求內容不正確' }
  if (typeof detail === 'string') return standard[detail] ?? (/\p{Script=Han}/u.test(detail) ? detail : `請求失敗（狀態碼 ${status}），請檢查服務狀態`)
  return `請求失敗（狀態碼 ${status}）`
}

export function dateTime(value?: string | null): string {
  if (!value) return '尚未記錄'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '時間格式無效'
  return new Intl.DateTimeFormat('zh-Hant-HK', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }).format(date)
}

export function nativeValidationMessage(validity: Partial<ValidityState>): string {
  if (validity.valueMissing) return '請填寫此欄位。'
  if (validity.typeMismatch) return '請輸入有效的網址或資料格式。'
  if (validity.tooShort) return '輸入內容過短，請依欄位要求補充。'
  if (validity.tooLong) return '輸入內容過長，請依欄位要求縮短。'
  if (validity.rangeUnderflow) return '輸入數值低於允許的下限。'
  if (validity.rangeOverflow) return '輸入數值超過允許的上限。'
  if (validity.stepMismatch) return '請依欄位要求輸入正確的數值間隔。'
  if (validity.badInput) return '請輸入有效的數值。'
  if (validity.patternMismatch) return '輸入格式不符合此欄位的要求。'
  return ''
}
