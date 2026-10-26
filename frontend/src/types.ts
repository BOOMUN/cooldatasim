export interface User { id: number; username: string; display_name: string; role: string }
export interface Auth { user: User; csrf_token: string }
export interface Contact { id: number; display_name: string; phone: string; tags: string[]; notes: string; attributes: Record<string, unknown>; language?: string }
export interface Message { id: number; body: string; kind: string; direction: string; sender_type: string; status: string; created_at: string; metadata: Record<string, unknown> }
export interface Conversation { id: number; contact: Contact; mode: string; status: string; unread_count: number; assigned_user_id: number | null; updated_at: string; sandbox: boolean; preview: string; messages?: Message[] }
export interface Source { id: number; name: string; url: string; status: string; max_pages: number; last_synced: string | null }
export interface JobResult { pages?: number; scope?: string; limit_reached?: boolean; remaining_discovered?: number; documents_changed?: number; products_changed?: number; errors?: { url: string; error: string }[] }
export interface Job { id: number; source_id: number; status: string; progress: number; error: string | null; result: JobResult | null; created_at: string }
export interface Document { id: number; source_id: number | null; title: string; url: string | null; category: string; content: string; status: string; revision: number; published_content: string | null; updated_at: string; vector_status: string }
export interface Product { id: number; name: string; sku: string | null; country: string | null; card_type: string | null; days: number | null; data_allowance: string | null; price: number | string | null; original_price: number | string | null; currency: string | null; url: string | null; status: string; verified_at: string | null }
export interface AIResult { answer: string; citations: { id: number; title: string; url: string }[]; status: string; trace: string[]; retrieval_mode: string }
export interface ChatIntegration { configured: boolean; provider: string; model: string; reasoning_effort: string | null; display_name: string }
export interface Integrations { chat?: ChatIntegration; qwen?: { configured: boolean; model: string }; embedding: { configured: boolean; model: string; dimensions: number }; reranker: { configured: boolean; model: string }; whatsapp: { configured: boolean; enabled: boolean; provider: string; instance: string } }
