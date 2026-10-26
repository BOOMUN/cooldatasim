import assert from 'node:assert/strict'
import test from 'node:test'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { parse as parseComponent } from '@vue/compiler-sfc'
import { parse as parseTemplate } from '@vue/compiler-dom'
import { STATUS_LABELS, categoryLabel, dateTime, diagnosticRows, languageLabel, messageKindLabel, nativeValidationMessage, serverErrorMessage, statusLabel, validationMessage } from '../src/localization.ts'

test('actual backend status codes display Traditional Chinese, including unknown fallbacks', () => {
  for (const key of ['text_only', 'new', 'limited', 'note', 'pending', 'failed', 'listed', 'model_not_listed', 'keyword', 'keyword_no_vectors', 'hybrid', 'implemented_unverified', 'metadata_only', 'not_implemented']) {
    assert.match(statusLabel(key), /\p{Script=Han}/u)
    assert.notEqual(statusLabel(key), key)
  }
  assert.equal(statusLabel('future_backend_state'), '未識別狀態')
  assert.equal(statusLabel(null), '尚未記錄')
})

test('language, attachment and known category codes have readable labels', () => {
  assert.equal(languageLabel('zh-HK'), '繁體中文（香港）')
  assert.equal(languageLabel('zh-Hans'), '簡體中文')
  assert.equal(languageLabel('en'), '英語')
  assert.equal(messageKindLabel('audio'), '語音')
  assert.equal(messageKindLabel('unknown_kind'), '未識別類型')
  assert.equal(categoryLabel('activation'), '啟用與使用')
})

test('localization does not convert user or website content', () => {
  // This simplified string is deliberately user-provided data, not UI copy.
  const customCategory = '用户自己填写的分类'
  assert.equal(categoryLabel(customCategory), customCategory)
})

test('nested service diagnostics translate system keys and enums while retaining model identifiers', () => {
  assert.deepEqual(diagnosticRows({ embedding: { model: 'Qwen3-Embedding-0.6B', configured: false, status: 'model_not_listed' }, capabilities: { media_send: 'not_implemented' } }), [
    { label: '向量模型 · 模型名稱', value: 'Qwen3-Embedding-0.6B' },
    { label: '向量模型 · 已設定', value: '否' },
    { label: '向量模型 · 狀態', value: '模型不在清單中' },
    { label: '功能能力 · 傳送媒體', value: '尚未實作' },
  ])
})

test('validation and HTTP errors do not leak framework English into the interface', () => {
  assert.equal(validationMessage({ type: 'string_too_short', loc: ['body', 'password'], ctx: { min_length: 16 } }), '密碼：至少需要 16 個字元')
  assert.equal(serverErrorMessage([{ type: 'greater_than_equal', loc: ['body', 'max_pages'], ctx: { ge: 1 }, msg: 'Input should be greater than or equal to 1' }], 422), '採集頁數上限：必須大於或等於 1')
  assert.equal(serverErrorMessage('Not Found', 404), '找不到要求的資料')
  assert.equal(serverErrorMessage('Unknown technical failure', 503), '請求失敗（狀態碼 503），請檢查服務狀態')
})

test('dates and browser-native form validation have Traditional Chinese fallbacks', () => {
  assert.equal(dateTime(null), '尚未記錄')
  assert.equal(dateTime('not-a-date'), '時間格式無效')
  assert.match(dateTime('2026-10-24T08:00:00Z'), /月/)
  assert.equal(nativeValidationMessage({ valueMissing: true }), '請填寫此欄位。')
  assert.equal(nativeValidationMessage({ rangeOverflow: true }), '輸入數值超過允許的上限。')
  assert.equal(nativeValidationMessage({ valid: true }), '')
})

test('static visible template copy and status labels contain no known simplified UI characters', () => {
  // Only literal template text and user-visible attributes are checked. Input
  // aliases, code identifiers, test fixtures, API values and website data are not.
  const simplifiedUI = /[关联网页发识进设备请确错误询载务户号码显传动应开闭记录项条数库写读让还没这过处检试览价签标线讯该点实种时离连输统态审据]/u
  const forbiddenHeadings = /WELCOME BACK|CUSTOMER CARE|CUSTOMER PROFILE|LOCAL WORKSPACE|PRODUCT REVIEW|KNOWLEDGE REVIEW|BUSINESS MESSAGING|GENERATION|EMBEDDING|RERANKING/
  function visit(node, file) {
    const texts = node.type === 2 ? [node.content] : node.type === 1 ? node.props.filter(prop => prop.type === 6 && ['title', 'placeholder', 'aria-label', 'alt'].includes(prop.name) && prop.value).map(prop => prop.value.content) : []
    for (const text of texts) {
      assert.doesNotMatch(text, simplifiedUI, `${file}: visible text ${text}`)
      assert.doesNotMatch(text, forbiddenHeadings, `${file}: untranslated heading ${text}`)
    }
    for (const child of node.children ?? []) visit(child, file)
  }
  function walk(directory) {
    for (const item of readdirSync(directory, { withFileTypes: true })) {
      const file = join(directory, item.name)
      if (item.isDirectory()) walk(file)
      else if (file.endsWith('.vue')) {
        const template = parseComponent(readFileSync(file, 'utf8')).descriptor.template
        if (template) visit(parseTemplate(template.content), file)
      }
    }
  }
  walk(fileURLToPath(new URL('../src', import.meta.url)))
  for (const text of Object.values(STATUS_LABELS)) assert.doesNotMatch(text, simplifiedUI)
})
