/**
 * Map from every error_code in the contract (plus NETWORK_DOWN) to a
 * short, plain-English message for the UI.
 * The UI never shows raw server text as its only message.
 */
export const ERROR_MESSAGES: Record<string, string> = {
  VALIDATION_ERROR: 'Some fields are invalid. Please check and try again.',
  NOT_FOUND: 'That item was not found.',
  UNAUTHORIZED: 'Please sign in again.',
  FORBIDDEN: 'Your account cannot do this.',
  LINK_EXPIRED: 'This link has expired or was turned off. Ask the centre for a new link.',
  RATE_LIMITED: 'Too many tries in a short time. Wait a minute and try again.',
  WRONG_SLOT: 'This action is not allowed for this slot.',
  INVALID_TRANSITION: 'This action is not allowed in the current state.',
  DUPLICATE_START: 'This job has already been started from another device.',
  EVIDENCE_MISSING: 'Take a photo first.',
  DRAFT_NOT_FOUND: 'The intake draft was not found.',
  READER_UNAVAILABLE: 'The document reader is temporarily unavailable.',
  PAYLOAD_TOO_LARGE: 'The file is too large. Maximum size is 8 MB.',
  NETWORK_DOWN: 'No signal. Your photo is still here. Try again.',
};

/**
 * Return a user-friendly message for any error_code.
 * Falls back to the raw code if unknown.
 */
export function friendlyError(code: string): string {
  return ERROR_MESSAGES[code] ?? `An unexpected error occurred (${code}).`;
}
