export const userFacingApiError = (error: unknown, fallback: string): string => {
  const message = error instanceof Error ? error.message : ''
  const code = typeof error === 'object' && error !== null && 'code' in error
    ? String(error.code)
    : ''
  if (/auth_session_expired|auth_session_revoked|authentication is required|unauthenticated/i.test(`${code} ${message}`)) {
    return '当前登录状态无法通过服务端验证，请重新登录后再试。'
  }
  return message || fallback
}
