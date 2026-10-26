import assert from 'node:assert/strict'
import test from 'node:test'
import { hasPublishedSnapshot, jobScopeSummary, jobStatusLabel } from '../src/knowledgePresentation.ts'

test('a draft revision retains its prior published snapshot', () => {
  assert.equal(hasPublishedSnapshot({ status: 'draft', published_content: 'Approved prior version' }), true)
  assert.equal(hasPublishedSnapshot({ status: 'draft', published_content: null }), false)
  assert.equal(hasPublishedSnapshot({ status: 'published', published_content: 'Approved' }), true)
})

test('withdrawn content is never described as an active snapshot', () => {
  assert.equal(hasPublishedSnapshot({ status: 'withdrawn', published_content: null }), false)
  assert.equal(hasPublishedSnapshot({ status: 'withdrawn', published_content: 'Historical text' }), false)
})

test('a bounded successful job makes the uncollected scope visible', () => {
  const job = { status: 'succeeded', result: { pages: 10, scope: 'bounded', limit_reached: true, remaining_discovered: 42 } }
  assert.equal(jobStatusLabel(job), '達採集上限')
  assert.equal(jobScopeSummary(job), '本批次已處理 10 頁；達頁數上限，仍有已發現頁面未採集（42 頁）。')
})

test('legacy job results do not imply a full-site crawl', () => {
  const job = { status: 'succeeded', result: { pages: 5 } }
  assert.equal(jobStatusLabel(job), '本批次已完成')
  assert.equal(jobScopeSummary(job), '本批次已處理 5 頁；僅反映本批次範圍，不代表全站已採集。')
})

test('missing and partial results do not invent page counts', () => {
  assert.equal(jobScopeSummary({ status: 'queued', result: null }), '本批次處理頁數尚未記錄；僅反映本批次範圍，不代表全站已採集。')
  assert.equal(jobScopeSummary({ status: 'partial', result: { pages: 3, remaining_discovered: 7 } }), '本批次已處理 3 頁；仍有 7 個已發現頁面未採集。')
})

test('a zero discovered remainder is not presented as uncollected pages', () => {
  assert.equal(jobScopeSummary({ status: 'limited', result: { pages: 10, limit_reached: true, remaining_discovered: 0 } }), '本批次已處理 10 頁；達頁數上限，本批次未記錄剩餘已發現頁面，不代表全站已採集。')
})
