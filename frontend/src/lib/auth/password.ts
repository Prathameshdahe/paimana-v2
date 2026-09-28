/**
 * src/lib/auth/password.ts
 *
 * The password policy as the backend enforces it (backend/auth: at least 12 characters, not a common password, not
 * containing the email's local part), checked here first so a form says what is wrong before it is sent, and a
 * strength score by rules: length and the mix of character classes. No library, and no dictionary beyond a short
 * list of the commonest passwords; the backend's list is the one that holds.
 */
export const MIN_LENGTH = 12

const COMMON = new Set([
  'password', 'password1', 'password12', 'password123', 'password1234', 'passw0rd', 'p@ssw0rd', 'password@123',
  'pass@123', 'pass@1234', '123456', '12345678', '123456789', '1234567890', '123456789012', 'qwerty', 'qwerty123',
  'qwertyuiop', 'letmein', 'welcome', 'welcome1', 'welcome123', 'admin', 'admin123', 'admin@123', 'administrator',
  'iloveyou', 'monkey', 'dragon', 'sunshine', 'princess', 'football', 'baseball', 'abc123', 'abcd1234', 'abcdefgh',
  '111111', '000000', 'india123', 'india@123', 'india@1234', 'paimana', 'paimana123', 'paimana@123', 'changeme',
  'changeme123', 'secret', 'trustno1', 'mospi123', 'mospi@123', 'ipmd@123', 'ipmd1234',
])

export interface PasswordCheck {
  /** the policy passes */
  ok: boolean
  /** what the policy rejects, in order; empty when ok */
  problems: string[]
  /** 0 nothing or too short .. 4 strong, by rules; never above 1 while the policy fails */
  score: 0 | 1 | 2 | 3 | 4
  label: 'Too short' | 'Weak' | 'Fair' | 'Good' | 'Strong'
}

const LABEL: Record<PasswordCheck['score'], PasswordCheck['label']> = {
  0: 'Too short', 1: 'Weak', 2: 'Fair', 3: 'Good', 4: 'Strong',
}

/** the email's local part, lower-cased, when it is long enough to mean anything */
function localPart(email: string | undefined): string | null {
  const local = (email ?? '').split('@')[0]?.trim().toLowerCase() ?? ''
  return local.length >= 3 ? local : null
}

export function checkPassword(password: string, email?: string): PasswordCheck {
  const problems: string[] = []
  const n = password.length
  const lower = password.toLowerCase()
  if (n < MIN_LENGTH) problems.push(`At least ${MIN_LENGTH} characters${n ? ` (${n} so far)` : ''}`)
  if (COMMON.has(lower) || COMMON.has(lower.replace(/[^a-z0-9]/g, ''))) problems.push('Not a common password')
  const local = localPart(email)
  if (local && lower.includes(local)) problems.push('Not containing the name part of your email')

  let score: PasswordCheck['score'] = 0
  if (n >= MIN_LENGTH) {
    const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((re) => re.test(password)).length
    let s = 1
    if (classes >= 2) s += 1
    if (classes >= 3 || n >= 16) s += 1
    if ((classes >= 3 && n >= 16) || n >= 20) s += 1
    score = Math.min(4, s) as PasswordCheck['score']
    if (problems.length) score = 1
  }
  return { ok: problems.length === 0, problems, score, label: LABEL[score] }
}

/** the policy in one line, shown under the password box */
export const POLICY_TEXT =
  `At least ${MIN_LENGTH} characters; not a common password and not the name part of your email. ` +
  'Longer and mixed (letters, digits, symbols) is stronger.'
