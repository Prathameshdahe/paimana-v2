/**
 * src/lib/chatStream.ts
 *
 * POST /api/chat and read its text/event-stream answer (contracts/assistant.ts). EventSource cannot POST or send
 * the viewer headers, so this is fetch + a ReadableStream reader + a small SSE parser: events are split on blank
 * lines, a chunk may end mid-line or mid-event (the rest waits for the next chunk), one chunk may hold several
 * events, `:` lines are comments (heartbeats) and `\r\n` line ends are read like `\n`. Unknown event names and
 * undecodable data are skipped, so a newer backend cannot break an older page.
 *
 * Errors, as ApiError (lib/api.ts): status 0 the backend is not reachable; 429 the rate limit, its message the
 * backend's JSON `detail` (which says when to ask again; else built from Retry-After); any other status with the
 * detail when there is one. A stream that breaks after the answer began is a StreamBroken (the backend was reached,
 * so it is not "offline"). Aborting the signal rejects with the fetch AbortError; the caller tells a stop from a
 * failure by `signal.aborted`.
 */
import { API_BASE, ApiError, url, viewerHeaders } from '@/lib/api'
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

/** a parsed message -> a typed chat event, or null for an unknown name or data that is not JSON */
export function toChatEvent(m: SSEMessage): ChatEvent | null {
  if (!EVENTS.has(m.event)) return null
  try {
    return { event: m.event, data: JSON.parse(m.data) } as ChatEvent
  } catch {
    return null
  }
}

/** the turns to send: earlier turns (text only, cut to MAX_CHARS) then the question, the last MAX_TURNS */
export function chatMessages(history: ChatTurn[], question: string): ChatTurn[] {
  const turns = [...history.filter((t) => t.content.trim()), { role: 'user' as const, content: question }]
  return turns.slice(-MAX_TURNS).map((t) => ({ role: t.role, content: t.content.slice(0, MAX_CHARS) }))
}

async function failure(res: Response): Promise<ApiError> {
  let detail = res.statusText || `HTTP ${res.status}`
  let body: unknown
  let given = false
  try {
    body = await res.json()
    const d = (body as { detail?: unknown } | null)?.detail
    if (typeof d === 'string') {
      detail = d
      given = true
    }
  } catch {
    // not a JSON error body
  }
  // the rate limit's detail says when to ask again; without one, the Retry-After header does
  const wait = Number(res.headers.get('Retry-After'))
  if (res.status === 429 && !given && wait > 0) detail = `Please try again in ${Math.ceil(wait)} seconds.`
  return new ApiError(res.status, detail, body)
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
      headers: { ...viewerHeaders(), 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(request),
      signal,
    })
  } catch (e) {
    if (signal?.aborted) throw e
    throw new ApiError(0, `backend not reachable at ${API_BASE}`)
  }
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
