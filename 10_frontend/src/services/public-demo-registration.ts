export interface PublicDemoOptions {
  site_key: string
  action: 'psynova_demo_signup'
}

export function isPublicDemoUsername(value: string): boolean {
  return value.length <= 128 && !/^(seed\.|demo\.|synthetic_)/i.test(value)
    && (/^[A-Za-z0-9][A-Za-z0-9._-]{3,127}$/.test(value)
      || /^[A-Za-z0-9][A-Za-z0-9._+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$/.test(value))
}

interface Turnstile {
  render: (container: HTMLElement, options: {
    sitekey: string
    action: string
    language: string
    size: 'flexible' | 'compact'
    callback: (token: string) => void
    'expired-callback': () => void
    'error-callback': () => void
  }) => string
  reset: (widgetId: string) => void
  remove: (widgetId: string) => void
}

const endpoint = '/api/v1/auth/public-demo'
const turnstileWindow = window as typeof window & { turnstile?: Turnstile }
let turnstileLoader: Promise<Turnstile> | undefined

export async function loadPublicDemoOptions(signal: typeof window.AbortSignal.prototype): Promise<PublicDemoOptions | null> {
  const response = await fetch(endpoint, { signal, cache: 'no-store', credentials: 'same-origin' })
  if (!response.ok) return null
  const data = (await response.json())?.data
  return typeof data?.site_key === 'string' && data.action === 'psynova_demo_signup' ? data : null
}

export function loadTurnstile(): Promise<Turnstile> {
  if (turnstileWindow.turnstile) return Promise.resolve(turnstileWindow.turnstile)
  if (!turnstileLoader) {
    turnstileLoader = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      const fail = () => {
        script.remove()
        turnstileLoader = undefined
        reject(new Error('人机验证暂时无法加载，请稍后重试。'))
      }
      const timer = window.setTimeout(fail, 12000)
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit'
      script.async = true
      script.onload = () => {
        window.clearTimeout(timer)
        if (turnstileWindow.turnstile) resolve(turnstileWindow.turnstile)
        else fail()
      }
      script.onerror = () => { window.clearTimeout(timer); fail() }
      document.head.append(script)
    })
  }
  return turnstileLoader
}

export async function createPublicDemoAccount(input: {
  username: string
  password: string
  turnstile_token: string
  synthetic_only: boolean
}): Promise<string> {
  const response = await fetch(endpoint, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (response.status === 409) throw new Error('账号已存在或验证码已使用。请换一个账号，重新验证。')
  if (response.status === 403) throw new Error('人机验证未通过，请重新验证。')
  if (response.status === 429) throw new Error('注册请求较多，请稍后再试。')
  if (response.status === 503) throw new Error('注册暂不可用，请稍后再试。')
  if (response.status !== 201) throw new Error('注册未完成，请检查填写的信息后重试。')
  const username = (await response.json())?.data?.username
  if (username !== input.username) throw new Error('请尝试用刚设置的账号登录。')
  return username
}
