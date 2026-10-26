import type { Document, Job } from './types'

export function hasPublishedSnapshot(document: Pick<Document, 'published_content' | 'status'>): boolean {
  return document.status !== 'withdrawn' && document.published_content != null
}

export function jobStatusLabel(job: Pick<Job, 'status' | 'result'>): string {
  if (job.result?.limit_reached) return '達採集上限'
  return ({ succeeded: '本批次已完成', completed: '本批次已完成', partial: '部分採集', limited: '達採集上限', failed: '採集失敗', running: '採集中', queued: '排隊中', pending: '等待中' } as Record<string, string>)[job.status] ?? '待確認'
}

export function jobScopeSummary(job: Pick<Job, 'status' | 'result'>): string {
  const result = job.result
  const pages = typeof result?.pages === 'number' ? `本批次已處理 ${result.pages} 頁` : '本批次處理頁數尚未記錄'
  if (result?.limit_reached) {
    if (result.remaining_discovered === 0) return `${pages}；達頁數上限，本批次未記錄剩餘已發現頁面，不代表全站已採集。`
    const remaining = typeof result.remaining_discovered === 'number' ? `（${result.remaining_discovered} 頁）` : ''
    return `${pages}；達頁數上限，仍有已發現頁面未採集${remaining}。`
  }
  if ((result?.remaining_discovered ?? 0) > 0) return `${pages}；仍有 ${result!.remaining_discovered} 個已發現頁面未採集。`
  return `${pages}；僅反映本批次範圍，不代表全站已採集。`
}
