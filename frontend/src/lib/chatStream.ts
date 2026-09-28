/**
 * src/lib/chatStream.ts
 *
 * POST /api/chat and read its text/event-stream answer (contracts/assistant.ts). EventSource cannot POST, so this is
 * fetch + a ReadableStream reader + a small SSE parser: events are split on blank lines, a chunk may end mid-line
 * or mid-event (the rest waits for the next chunk), one chunk may hold several events, `:` lines are comments
 * (heartbeats) and `\r\n` line ends are read like `\n`. Unknown event names and undecodable data are skipped, so a
 * newer backend cannot break an older page. The session cookie names the viewer and, when signed in, the CSRF
 * token goes along as the POST needs (lib/api.ts authHeaders); the public sends neither.
 *
 * Errors, as ApiError (lib/api.ts): status 0 the backend is not reachable; 429 the rate limit, its message the
 * backend's JSON `detail` (which says when to ask again; else built from Retry-After); 401 a session that is gone
 * (the session context is told, as for any call); any other status with the detail when there is one. A stream
 * that breaks after the answer began is a StreamBroken (the backend was reached, so it is not "offline"). Aborting
 * the signal rejects with the fetch AbortError; the caller tells a stop from a failure by `signal.aborted`.
 */
import { API_BASE, ApiError, authHeaders, failure, reportUnauthorized, url } from '@/lib/api'
import type { ChatEvent, ChatEventName, ChatRequest, ChatTurn } from '@/contracts/assistant'

/** the connection broke after the answer began streaming: the backend is up, the answer is cut short */
export class StreamBroken extends Error {
  constructor(message = 'The connection broke off mid-answer; ask again.') {
    super(message)
    this.name = 'StreamBroken'
  }
}

/** SPEC 4: at most 12 turns of at most 1000 characters */
export const MAX_TURNS = 12
export const MAX_CHARS = 1000

export interface SSEMessage {
  event: string
  data: string
}

const EVENTS: ReadonlySet<string> = new Set<ChatEventName>(['status', 'tool', 'card', 'token', 'retry', 'done', 'error'])

/** one event block (no blank lines inside) -> its name and data; null for a comment-only or empty block */
function parseBlock(block: string): SSEMessage | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const i = line.indexOf(':')
    const field = i < 0 ? line : line.slice(0, i)
    // one optional space after the colon is part of the syntax, not the value
    const value = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '')
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
    // id: and retry: mean nothing to a one-shot POST stream
  }
  return data.length ? { event, data: data.join('\n') } : null
}

/**
 * An incremental SSE parser: push() each decoded chunk and get back the events it completed; flush() at the end
 * of the stream returns an event the server did not close with a blank line.
 */
export function createSSEParser() {
  let buffer = ''
  return {
    push(chunk: string): SSEMessage[] {
      let text = buffer + chunk
      // a trailing \r may be the first half of a \r\n split across chunks: keep it back
      const carry = text.endsWith('\r') ? '\r' : ''
      if (carry) text = text.slice(0, -1)
      text = text.replace(/\r\n?/g, '\n')
      const cut = text.lastIndexOf('\n\n')
      if (cut < 0) {
        buffer = text + carry
        return []
      }
      buffer = text.slice(cut + 2) + carry
      return text.slice(0, cut).split('\n\n').map(parseBlock).filter((m): m is SSEMessage => m !== null)
    },
    flush(): SSEMessage[] {
      const rest = buffer.replace(/\r\n?/g, '\n')
      buffer = ''
      const m = rest.trim() ? parseBlock(rest) : null
      return m ? [m] : []
    },
  }
}

type Fields = Record<string, unknown>

/**
 * The fields each event must carry for the chat to fold it into an answer: an event without them is dropped here,
 * since the fold runs in the chat's state update, above any per-answer error boundary.
 */
const SHAPE: Record<ChatEventName, (d: Fields) => boolean> = {
  status: (d) => typeof d.stage === 'string',
  tool: (d) => typeof d.id === 'string' || typeof d.id === 'number',
  card: (d) => typeof d.type === 'string' && (d.type !== 'sources' || Array.isArray(d.items)),
  token: (d) => typeof d.text === 'string',
  retry: (d) => Array.isArray(d.reasons),
  done: (d) => typeof d.text === 'string',
  error: (d) => typeof d.message === 'string',
}

/**
 * a parsed message -> a typed chat event, or null for an unknown name, data that is not JSON or not an object
 * (`data: null`), or an object without the fields its event needs
 */
export function toChatEvent(m: SSEMessage): ChatEvent | null {
  if (!EVENTS.has(m.event)) return null
  let data: unknown
  try {
    data = JSON.parse(m.data)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null
  if (!SHAPE[m.event as ChatEventName](data as Fields)) return null
  return { event: m.event, data } as ChatEvent
}

/** the turns to send: earlier turns (text only, cut to MAX_CHARS) then the question, the last MAX_TURNS */
export function chatMessages(history: ChatTurn[], question: string): ChatTurn[] {
  const turns = [...history.filter((t) => t.content.trim()), { role: 'user' as const, content: question }]
  return turns.slice(-MAX_TURNS).map((t) => ({ role: t.role, content: t.content.slice(0, MAX_CHARS) }))
}

/**
 * Asks the assistant and calls onEvent for every event as it arrives; resolves when the stream ends (normally
 * after `done` or `error`). Rejects with an ApiError, or the AbortError when `signal` is aborted.
 */
export async function streamChat(
  request: ChatRequest,
  onEvent: (e: ChatEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  let res: Response
  try {
    res = await fetch(url('/api/chat'), {
      method: 'POST',
      headers: { ...authHeaders(), 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(request),
      credentials: 'include',
      signal,
    })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new ApiError(0, `backend not reachable at ${API_BASE || window.location.origin}`)
  }
  if (res.status === 401) reportUnauthorized()
  if (!res.ok) throw await failure(res)
  if (!res.body) throw new ApiError(res.status, 'the answer came without a stream')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const parser = createSSEParser()
  const emit = (messages: SSEMessage[]) => {
    for (const m of messages) {
      const e = toChatEvent(m)
      if (e) onEvent(e)
    }
  }
  for (;;) {
    let chunk: ReadableStreamReadResult<Uint8Array>
    try {
      chunk = await reader.read()
    } catch (e) {
      if (signal?.aborted) throw e
      throw new StreamBroken()
    }
    if (chunk.done) break
    emit(parser.push(decoder.decode(chunk.value, { stream: true })))
  }
  emit(parser.push(decoder.decode()))
  emit(parser.flush())
}
