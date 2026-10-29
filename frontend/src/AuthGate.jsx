import { useEffect, useRef, useState } from 'react'
import { motion, useReducedMotion, useSpring } from 'motion/react'
import { Eye, EyeOff, Hexagon, LoaderCircle, LockKeyhole, UserRound } from 'lucide-react'
import App from './App'
import { authFetch } from './authClient'
import './AuthGate.css'

export default function AuthGate() {
  const [owner, setOwner] = useState(null)
  const [checking, setChecking] = useState(true)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [connectionFailed, setConnectionFailed] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const username = useRef()
  const reduced = useReducedMotion()
  const backgroundX = useSpring(0, { stiffness: 75, damping: 28 })
  const backgroundY = useSpring(0, { stiffness: 75, damping: 28 })

  function moveBackground(event) {
    if (reduced || event.pointerType !== 'mouse') return
    const bounds = event.currentTarget.getBoundingClientRect()
    backgroundX.set(((event.clientX - bounds.left) / bounds.width - 0.5) * 14)
    backgroundY.set(((event.clientY - bounds.top) / bounds.height - 0.5) * 10)
  }

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    async function check() {
      setChecking(true)
      try {
        const response = await authFetch('/auth/me', { cache: 'no-store', signal: controller.signal })
        if (!active) return
        if (response.status === 401) { setOwner(null); setConnectionFailed(false); return }
        if (!response.ok) throw new Error('Your cloud is temporarily unavailable. Try again.')
        const account = await response.json()
        if (active) { setOwner(account); setConnectionFailed(false); setError('') }
      } catch (failure) {
        if (active) { setError(controller.signal.aborted ? 'Your cloud took too long to respond. Try again.' : failure.message); setConnectionFailed(true) }
      } finally { if (active) setChecking(false) }
    }
    const timer = setTimeout(() => controller.abort(), 30000)
    check()
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [attempt])

  useEffect(() => {
    if (!owner) return undefined
    const refresh = () => { if (!document.hidden) setAttempt((value) => value + 1) }
    const timer = setInterval(refresh, 60000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { clearInterval(timer); window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [owner])

  useEffect(() => {
    const signedOut = () => { setOwner(null); setPending(false); setError('Your session ended. Please sign in again.') }
    window.addEventListener('homesphere:signed-out', signedOut)
    return () => window.removeEventListener('homesphere:signed-out', signedOut)
  }, [])

  useEffect(() => { if (!checking && !owner) username.current?.focus() }, [checking, owner])

  async function signIn(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    setPending(true)
    setError('')
    try {
      const response = await authFetch('/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: data.get('username'), password: data.get('password') }),
        signal: AbortSignal.timeout(30000),
      })
      if (!response.ok) {
        const result = await response.json().catch(() => ({}))
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Sign-in failed. Please try again.')
      }
      const account = await response.json()
      form.reset()
      setShowPassword(false)
      setOwner(account)
    } catch (failure) { setError(failure.name === 'TimeoutError' ? 'Sign-in timed out. Please try again.' : failure.message) }
    finally { setPending(false) }
  }

  async function signOut() {
    setPending(true)
    setError('')
    try {
      const response = await authFetch('/auth/logout', { method: 'POST', signal: AbortSignal.timeout(15000) })
      if (!response.ok) throw new Error('Could not sign out. Try again.')
      setOwner(null)
    } catch (failure) { setError(failure.message) }
    finally { setPending(false) }
  }

  if (owner) return <><App owner={owner} onLogout={signOut} loggingOut={pending} />{error && <div className="auth-session-error" role="alert">{error}<button onClick={() => setError('')} aria-label="Dismiss sign-out error">Dismiss</button></div>}</>

  return <main className="auth-page" onPointerMove={moveBackground} onPointerLeave={() => { backgroundX.set(0); backgroundY.set(0) }}>
    <motion.img className="auth-background" src="/login-ribbon.webp" alt="" aria-hidden="true" draggable={false} fetchPriority="high" style={{ x: reduced ? 0 : backgroundX, y: reduced ? 0 : backgroundY, scale: reduced ? 1 : 1.025 }} initial={reduced ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.65 }} />
    <header className="auth-header"><div className="auth-brand"><Hexagon size={25} strokeWidth={1.4} aria-hidden="true" /><span>HOMESPHERE<small>Your personal cloud</small></span></div><span className="auth-local"><LockKeyhole size={12} aria-hidden="true" />PRIVATE CLOUD</span></header>
    <div className="auth-layout">
      <motion.section className="auth-card" aria-labelledby="signin-title" initial={reduced ? false : { opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
        <h1 id="signin-title">Welcome home.</h1><p className="auth-subtitle">Sign in to your personal cloud.</p>
        {checking ? <div className="auth-checking" role="status"><LoaderCircle className="spin" size={24} aria-hidden="true" /><span>Opening your cloud…</span></div>
          : connectionFailed ? <div className="auth-connection"><p role="alert">{error}</p><button className="auth-submit" onClick={() => setAttempt((value) => value + 1)}>Try again</button></div>
          : <form onSubmit={signIn} className="auth-form" aria-busy={pending}>
            <label htmlFor="owner-username">Username</label><div className="auth-input"><UserRound className="auth-field-icon" size={17} strokeWidth={1.5} aria-hidden="true" /><input ref={username} id="owner-username" name="username" placeholder="Your username" autoComplete="username" autoCapitalize="none" spellCheck="false" required maxLength={64} disabled={pending} aria-describedby={error ? 'signin-error' : undefined} /></div>
            <label htmlFor="owner-password">Password</label><div className="auth-password"><LockKeyhole className="auth-field-icon" size={17} strokeWidth={1.5} aria-hidden="true" /><input id="owner-password" name="password" placeholder="Your password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required maxLength={128} disabled={pending} aria-describedby={error ? 'signin-error' : undefined} /><button type="button" onClick={() => setShowPassword((value) => !value)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword} disabled={pending}>{showPassword ? <EyeOff size={18} strokeWidth={1.5} aria-hidden="true" /> : <Eye size={18} strokeWidth={1.5} aria-hidden="true" />}</button></div>
            {error && <p className="auth-error" id="signin-error" role="alert">{error}</p>}
            <button type="submit" className="auth-submit" disabled={pending}>{pending ? <><LoaderCircle className="spin" size={18} aria-hidden="true" />Signing in…</> : 'Log in'}</button>
            <p className="auth-footnote"><LockKeyhole size={12} aria-hidden="true" />Signed in for up to 8 hours</p>
          </form>}
      </motion.section>
    </div><footer className="auth-footer"><span>HOMESPHERE / PERSONAL CLOUD</span><span>Your files. Your server. Your control.</span></footer>
  </main>
}
