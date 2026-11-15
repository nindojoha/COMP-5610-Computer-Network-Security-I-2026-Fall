import { useState } from 'react'
import './Auth.css'

function Auth({ onAuthenticated, initialError = '' }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(initialError)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (isSubmitting) return

    setError('')
    setIsSubmitting(true)
    try {
      const response = await fetch(
        mode === 'login' ? '/api/auth/login' : '/api/auth/register',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email,
            password,
            ...(mode === 'register' ? { display_name: displayName } : {}),
          }),
        },
      )
      const result = await response.json()
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to authenticate. Please try again.')
      }

      onAuthenticated(result.user)
    } catch (requestError) {
      setError(
        requestError instanceof TypeError
          ? 'Unable to reach the server. Check that the backend is running and try again.'
          : requestError instanceof Error
          ? requestError.message
          : 'Unable to authenticate. Please try again.',
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  const registering = mode === 'register'

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand">
          <span className="auth-brand-mark" aria-hidden="true">N</span>
          <span>Nexus</span>
        </div>
        <span className="auth-eyebrow">YOUR PERSONAL WORKSPACE</span>
        <h1 id="auth-title">{registering ? 'Create your account' : 'Welcome back'}</h1>
        <p className="auth-subtitle">
          {registering
            ? 'Create an account to keep your calendar and workspace private.'
            : 'Sign in to continue to your workspace.'}
        </p>

        <form className="auth-form" onSubmit={submit}>
          {registering && (
            <label>
              Name
              <input
                autoComplete="name"
                maxLength={80}
                onChange={(event) => setDisplayName(event.target.value)}
                required
                value={displayName}
              />
            </label>
          )}
          <label>
            Email
            <input
              autoComplete="email"
              onChange={(event) => setEmail(event.target.value)}
              required
              type="email"
              value={email}
            />
          </label>
          <label>
            Password
            <input
              autoComplete={registering ? 'new-password' : 'current-password'}
              maxLength={128}
              minLength={registering ? 10 : 1}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
            {registering && <span className="auth-hint">Use at least 10 characters.</span>}
          </label>
          {error && <p className="auth-error" role="alert">{error}</p>}
          <button className="auth-submit" disabled={isSubmitting} type="submit">
            {isSubmitting
              ? 'Please wait...'
              : registering
              ? 'Create account'
              : 'Sign in'}
          </button>
        </form>

        <p className="auth-mode-switch">
          {registering ? 'Already have an account?' : 'New to Nexus?'}
          <button
            onClick={() => {
              setMode(registering ? 'login' : 'register')
              setError('')
            }}
            type="button"
          >
            {registering ? 'Sign in' : 'Create an account'}
          </button>
        </p>
      </section>
    </main>
  )
}

export default Auth
