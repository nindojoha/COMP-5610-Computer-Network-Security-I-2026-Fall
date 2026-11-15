import { useCallback, useEffect, useRef, useState } from 'react'
import CalendarView from './Calendar.jsx'
import Auth from './Auth.jsx'
import CurrentDateTime from './CurrentDateTime.jsx'
import { toLocalDateTime } from './localDateTime.js'
import './App.css'

const tools = [
  { name: 'New chat', icon: 'plus' },
  { name: 'Explore', icon: 'search' },
  { name: 'Calendar', icon: 'calendar' },
  { name: 'Code assistant', icon: 'code' },
  { name: 'Files', icon: 'folder' },
  { name: 'Saved chats', icon: 'bookmark' },
]

const initialTasks = [
  { id: 1, title: 'Review network security notes', completed: false },
  { id: 2, title: 'Finish the lab write-up', completed: false },
  { id: 3, title: 'Prepare for the next exam', completed: true },
  { id: 4, title: 'Check project updates', completed: false },
  { id: 5, title: 'Plan a study session', completed: false },
]

const iconPaths = {
  bookmark: (
    <path d="M6 4.75h12a1 1 0 0 1 1 1V21l-7-4-7 4V5.75a1 1 0 0 1 1-1Z" />
  ),
  calendar: (
    <>
      <rect x="3.5" y="5" width="17" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3.5 10h17" />
    </>
  ),
  check: <path d="m5 12 4 4L19 6" />,
  code: (
    <>
      <path d="m8 8-4 4 4 4" />
      <path d="m16 8 4 4-4 4" />
      <path d="m14 4-4 16" />
    </>
  ),
  folder: (
    <path d="M3.5 7.5a2 2 0 0 1 2-2h5l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2Z" />
  ),
  message: (
    <path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.5-3.5A7.5 7.5 0 1 1 20 11.5Z" />
  ),
  plus: (
    <>
      <path d="M12 5v14" />
      <path d="M5 12h14" />
    </>
  ),
  search: (
    <>
      <circle cx="10.8" cy="10.8" r="6.8" />
      <path d="m16 16 4 4" />
    </>
  ),
  send: (
    <>
      <path d="M12 19V5" />
      <path d="m5 12 7-7 7 7" />
    </>
  ),
  settings: (
    <>
      <path d="M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z" />
      <path d="m19.4 15 .1.1a1.8 1.8 0 0 1-2.5 2.5l-.1-.1a1.8 1.8 0 0 0-3 .9v.2a1.8 1.8 0 0 1-3.6 0v-.2a1.8 1.8 0 0 0-3-.9l-.1.1a1.8 1.8 0 0 1-2.5-2.5l.1-.1a1.8 1.8 0 0 0-.9-3h-.2a1.8 1.8 0 0 1 0-3.6h.2a1.8 1.8 0 0 0 .9-3l-.1-.1a1.8 1.8 0 0 1 2.5-2.5l.1.1a1.8 1.8 0 0 0 3-.9v-.2a1.8 1.8 0 0 1 3.6 0v.2a1.8 1.8 0 0 0 3 .9l.1-.1a1.8 1.8 0 0 1 2.5 2.5l-.1.1a1.8 1.8 0 0 0 .9 3h.2a1.8 1.8 0 0 1 0 3.6h-.2a1.8 1.8 0 0 0-.9 3Z" />
    </>
  ),
  sparkle: (
    <>
      <path d="m12 3 1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2L12 3Z" />
      <path d="m19 14 .9 2.1L22 17l-2.1.9L19 20l-.9-2.1L16 17l2.1-.9L19 14Z" />
    </>
  ),
}

function Icon({ name, size = 20 }) {
  return (
    <svg
      aria-hidden="true"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {iconPaths[name]}
    </svg>
  )
}

function formatEventTimeRange(event) {
  const [hour, minute] = event.time.split(':').map(Number)
  const endTotal = hour * 60 + minute + (event.duration_minutes || 15)
  const endMinutes = endTotal % (24 * 60)
  const dayOffset = Math.floor(endTotal / (24 * 60))
  const endTime = `${String(Math.floor(endMinutes / 60)).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`
  return `${event.time}–${endTime}${dayOffset ? ` (+${dayOffset}d)` : ''}`
}

function App() {
  const [authStatus, setAuthStatus] = useState('loading')
  const [authError, setAuthError] = useState('')
  const [user, setUser] = useState(null)
  const [activeTool, setActiveTool] = useState('New chat')
  const [tasks, setTasks] = useState(initialTasks)
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [isSending, setIsSending] = useState(false)
  const [resolvingProposal, setResolvingProposal] = useState(null)
  const [files, setFiles] = useState([])
  const [fileSearch, setFileSearch] = useState('')
  const [isUploading, setIsUploading] = useState(false)
  const [fileError, setFileError] = useState('')
  const fileInputRef = useRef(null)

  useEffect(() => {
    let active = true
    fetch('/api/auth/me')
      .then(async (response) => {
        const result = await response.json()
        if (!active) return
        if (response.ok) {
          setUser(result.user)
          setAuthStatus('signed-in')
        } else if (response.status === 401) {
          setAuthStatus('signed-out')
        } else {
          throw new Error(result.detail || 'Unable to verify your session.')
        }
      })
      .catch((error) => {
        if (!active) return
        setAuthError(
          error instanceof TypeError
            ? 'Unable to reach the server. Check that the backend is running and try again.'
            : error instanceof Error
            ? error.message
            : 'Unable to verify your session.',
        )
        setAuthStatus('signed-out')
      })
    return () => {
      active = false
    }
  }, [])

  const completedTasks = tasks.filter((task) => task.completed).length

  useEffect(() => {
    if (activeTool !== 'Files') return
    let active = true
    const query = fileSearch.trim()
    const timer = setTimeout(() => fetch(`/api/files${query ? `?query=${encodeURIComponent(query)}` : ''}`)
      .then(async (response) => {
        const result = await response.json()
        if (!active) return
        if (!response.ok) throw new Error(result.detail || 'Unable to load files.')
        setFiles(result.files || [])
        setFileError('')
      })
      .catch((error) => {
        if (active) setFileError(error instanceof Error ? error.message : 'Unable to load files.')
      }), 300)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [activeTool, fileSearch])

  async function uploadFile(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setIsUploading(true)
    setFileError('')
    try {
      const body = new FormData()
      body.append('file', file)
      const response = await fetch('/api/files', { method: 'POST', body })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Unable to upload file.')
      setFiles((currentFiles) => [result.file, ...currentFiles])
      setActiveTool('Files')
    } catch (error) {
      setFileError(error instanceof Error ? error.message : 'Unable to upload file.')
    } finally {
      setIsUploading(false)
    }
  }

  async function removeFile(fileId) {
    try {
      const response = await fetch(`/api/files/${fileId}`, { method: 'DELETE' })
      const result = await response.json()
      if (!response.ok) throw new Error(result.detail || 'Unable to delete file.')
      setFiles((currentFiles) => currentFiles.filter((file) => file.id !== fileId))
    } catch (error) {
      setFileError(error instanceof Error ? error.message : 'Unable to delete file.')
    }
  }

  function toggleTask(taskId) {
    setTasks((currentTasks) =>
      currentTasks.map((task) =>
        task.id === taskId ? { ...task, completed: !task.completed } : task,
      ),
    )
  }

  function handleAuthenticated(authenticatedUser) {
    setUser(authenticatedUser)
    setAuthError('')
    setMessages([])
    setPrompt('')
    setActiveTool('New chat')
    setResolvingProposal(null)
    setAuthStatus('signed-in')
  }

  const handleUnauthorized = useCallback((message) => {
    setAuthError(message)
    setAuthStatus('signed-out')
    setMessages([])
    setPrompt('')
    setActiveTool('New chat')
    setResolvingProposal(null)
  }, [])

  async function signOut() {
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST' })
      if (response.status === 401) {
        setMessages([])
        setUser(null)
        setPrompt('')
        setActiveTool('New chat')
        setResolvingProposal(null)
        setAuthStatus('signed-out')
        setAuthError('Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        const result = await response.json()
        throw new Error(result.detail || 'Unable to sign out.')
      }
      setMessages([])
      setUser(null)
      setPrompt('')
      setActiveTool('New chat')
      setResolvingProposal(null)
      setAuthStatus('signed-out')
      setAuthError('')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Unable to sign out.')
    }
  }

  async function resolveChatConflict(proposal, resolution) {
    setResolvingProposal(proposal.proposal_id)
    try {
      const response = await fetch(
        `/api/calendar/proposals/${proposal.proposal_id}/resolve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ resolution }),
        },
      )
      const result = await response.json()
      if (response.status === 401) {
        handleUnauthorized(result.detail || 'Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        if (response.status === 409 && result.detail?.status === 'conflict') {
          const nextProposal = {
            proposal_id: result.detail.proposal_id,
            title: result.detail.event.title,
            date: result.detail.event.date,
            time: result.detail.event.time,
            duration_minutes: result.detail.event.duration_minutes,
            conflicts: result.detail.conflicts,
            conflict_count: result.detail.conflict_count,
            occurrence_count: result.detail.occurrence_count,
          }
          setMessages((currentMessages) =>
            currentMessages.map((message) =>
              message.pendingConflict?.proposal_id === proposal.proposal_id
                ? { ...message, pendingConflict: nextProposal }
                : message,
            ),
          )
          return
        }
        throw new Error(result.detail || 'Unable to resolve this calendar conflict.')
      }

      setMessages((currentMessages) => [
        ...currentMessages.map((message) =>
          message.pendingConflict?.proposal_id === proposal.proposal_id
            ? { ...message, pendingConflict: null }
            : message,
        ),
        {
          role: 'assistant',
          content: resolution === 'reject'
            ? 'Scheduling canceled. No calendar changes were made.'
            : resolution === 'override'
              ? `"${proposal.title}" was scheduled, replacing the conflicting event(s).`
              : `"${proposal.title}" was scheduled alongside the existing event(s).`,
        },
      ])
    } catch (error) {
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          role: 'error',
          content: error instanceof Error ? error.message : 'Unable to resolve this conflict.',
        },
      ])
    } finally {
      setResolvingProposal(null)
    }
  }

  async function submitPrompt(event) {
    event.preventDefault()
    const message = prompt.trim()
    if (!message || isSending) return

    const history = messages
      .filter((chatMessage) => chatMessage.role === 'user' || chatMessage.role === 'assistant')
      .map((chatMessage) => ({
        role: chatMessage.role === 'assistant' ? 'model' : 'user',
        content: chatMessage.content,
      }))
    setMessages((currentMessages) => [
      ...currentMessages,
      { role: 'user', content: message },
    ])
    setPrompt('')
    setIsSending(true)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          history,
          client_datetime: toLocalDateTime(new Date()),
        }),
      })
      let result
      try {
        result = await response.json()
      } catch {
        throw new Error('The chat service returned an unreadable response. Please try again.')
      }

      if (!response.ok) {
        if (response.status === 401) {
          setAuthStatus('signed-out')
          setAuthError(result.detail || 'Your session expired. Please sign in again.')
        }
        throw new Error(result.detail || 'The assistant could not complete your request.')
      }
      if (typeof result.reply !== 'string' || !result.reply.trim()) {
        throw new Error('The assistant returned an empty reply. Please try again.')
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        {
          role: 'assistant',
          content: result.pending_conflict
            ? 'I found a calendar conflict. Nothing has been changed. Review the event times and choose how to proceed below.'
            : result.reply,
          pendingConflict: result.pending_conflict,
        },
      ])
    } catch (error) {
      setMessages((currentMessages) => [
        ...currentMessages,
        {
          role: 'error',
          content:
            error instanceof TypeError
              ? 'Unable to connect to the chat backend. Make sure it is running and try again.'
              : error instanceof Error
              ? error.message
              : 'Unable to reach the assistant. Please try again.',
        },
      ])
    } finally {
      setIsSending(false)
    }
  }

  if (authStatus === 'loading') {
    return <main className="auth-loading" aria-label="Loading account">Loading Nexus...</main>
  }

  if (authStatus !== 'signed-in') {
    return <Auth onAuthenticated={handleAuthenticated} initialError={authError} />
  }

  return (
    <div className="app-shell">
      <aside className="sidebar left-sidebar" aria-label="Main navigation">
        <a className="brand" href="#" aria-label="Nexus home">
          <span className="brand-mark">
            <Icon name="sparkle" size={19} />
          </span>
          <span>Nexus</span>
        </a>

        <nav className="tool-list" aria-label="Tools">
          {tools.map((tool) => (
            <button
              className={`tool-link${activeTool === tool.name ? ' active' : ''}`}
              aria-label={tool.name}
              key={tool.name}
              onClick={() => setActiveTool(tool.name)}
              type="button"
            >
              <Icon name={tool.icon} />
              <span>{tool.name}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <button
            className="tool-link footer-link"
            onClick={() => setSettingsOpen((open) => !open)}
            type="button"
          >
            <Icon name="settings" />
            <span>Settings</span>
          </button>
          <button className="profile-button" onClick={signOut} type="button" aria-label="Sign out">
            <span className="avatar">{user.display_name.slice(0, 1).toUpperCase()}</span>
            <span className="profile-name">{user.display_name}</span>
            <span className="profile-plan">Personal</span>
          </button>
        </div>
      </aside>

      {activeTool === 'Calendar' ? (
        <main className="calendar-panel">
          <CalendarView onUnauthorized={handleUnauthorized} />
        </main>
      ) : activeTool === 'Files' ? (
        <FilesPanel
          error={fileError}
          files={files}
          onDelete={removeFile}
          onSearch={setFileSearch}
          search={fileSearch}
        />
      ) : (
      <main className="chat-panel">
        <header className="topbar">
          <span className="topbar-message">message for checking in</span>
          {authError && <span className="topbar-error" role="alert">{authError}</span>}
          <button className="mobile-profile" onClick={signOut} type="button" aria-label="Sign out">
            {user.display_name.slice(0, 1).toUpperCase()}
          </button>
        </header>

        <section className={`chat-content${messages.length ? ' has-messages' : ''}`}>
          {messages.length === 0 ? (
            <div className="welcome">
              <div className="welcome-icon">
                <Icon name="sparkle" size={24} />
              </div>
              <h1>Hello there. What can I help you with?</h1>
              <p>Ask a question, explore an idea, or get something done.</p>
            </div>
          ) : (
            <div className="message-list" aria-live="polite">
              {messages.map((message, index) =>
                message.pendingConflict ? (
                  <div className="chat-message assistant-message conflict-message" key={`${index}-conflict`}>
                    <p>{message.content}</p>
                    <ConflictActions
                      disabled={resolvingProposal === message.pendingConflict.proposal_id}
                      onResolve={(resolution) => resolveChatConflict(message.pendingConflict, resolution)}
                      proposal={message.pendingConflict}
                    />
                  </div>
                ) : (
                  <p
                    className={`chat-message ${message.role}-message`}
                    key={`${index}-${message.role}`}
                  >
                    {message.content}
                  </p>
                ),
              )}
              {isSending && <p className="assistant-message typing-indicator">Thinking...</p>}
            </div>
          )}

          <div className="composer-wrap">
            <form className="composer" onSubmit={submitPrompt}>
              <input
                accept=".pdf,.txt,application/pdf,text/plain"
                className="file-input"
                onChange={uploadFile}
                ref={fileInputRef}
                type="file"
              />
              <textarea
                aria-label="Message Nexus"
                onChange={(event) => setPrompt(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault()
                    event.currentTarget.form.requestSubmit()
                  }
                }}
                placeholder="Message Nexus..."
                rows={2}
                value={prompt}
              />
              <div className="composer-actions">
                <div className="composer-leading-actions">
                  <button
                    aria-label="Upload a file"
                    className="attach-button"
                    disabled={isUploading}
                    onClick={() => fileInputRef.current?.click()}
                    type="button"
                  >
                    <Icon name="plus" size={18} />
                  </button>
                  <span className="composer-hint">
                    {isUploading ? 'Embedding file...' : 'Shift + Enter for a new line'}
                  </span>
                </div>
                <button
                  className="send-button"
                  type="submit"
                  aria-label="Send message"
                  disabled={!prompt.trim() || isSending}
                >
                  <Icon name="send" size={18} />
                </button>
              </div>
            </form>

            <div className="composer-footer">
              <div className="composer-settings">
                <button
                  aria-expanded={settingsOpen}
                  className="settings-trigger"
                  onClick={() => setSettingsOpen((open) => !open)}
                  type="button"
                >
                  <Icon name="settings" size={17} />
                  <span>Settings</span>
                </button>
                {settingsOpen && (
                  <div className="settings-popover">
                    <span className="popover-label">Response style</span>
                    <span className="popover-value">Balanced</span>
                  </div>
                )}
              </div>
              <CurrentDateTime />
            </div>
          </div>
        </section>
      </main>
      )}

      <aside className="sidebar tasks-sidebar" aria-label="Task list">
        <div className="tasks-heading">
          <div>
            <span className="eyebrow">YOUR WORKSPACE</span>
            <h2>Tasks</h2>
          </div>
          <span className="task-count">{completedTasks}/{tasks.length}</span>
        </div>
        <p className="tasks-subtitle">A little progress adds up.</p>

        <div className="task-list">
          {tasks.map((task) => (
            <label className="task-row" key={task.id}>
              <input
                checked={task.completed}
                onChange={() => toggleTask(task.id)}
                type="checkbox"
              />
              <span className="custom-checkbox">
                <Icon name="check" size={14} />
              </span>
              <span className="task-title">{task.title}</span>
            </label>
          ))}
        </div>
        <div className="tasks-footer">
          <span className="tasks-footer-icon">
            <Icon name="message" size={18} />
          </span>
          <span>Keep your day moving, one step at a time.</span>
        </div>
      </aside>
    </div>
  )
}

function ConflictActions({ disabled, onResolve, proposal }) {
  const conflictCount = proposal.conflict_count ?? proposal.conflicts.length

  return (
    <div className="conflict-actions">
      <div className="conflict-summary">
        <strong>Not scheduled yet: {proposal.title}</strong>
        <span>
          {proposal.occurrence_count > 1
            ? `${proposal.occurrence_count} recurring occurrences starting `
            : ''}{proposal.date} · {formatEventTimeRange(proposal)} overlaps:
        </span>
        <ul className="conflict-summary-list">
          {proposal.conflicts.map((event) => (
            <li key={event.id}>
              <strong>{event.title}</strong>
              <span>{event.date} · {formatEventTimeRange(event)}</span>
            </li>
          ))}
        </ul>
        <span>
          {conflictCount > proposal.conflicts.length
            ? `Showing ${proposal.conflicts.length} of ${conflictCount} conflicts. `
            : ''}Nothing has changed. Choose how to proceed:
        </span>
      </div>
      <div className="conflict-buttons">
        <button disabled={disabled} onClick={() => onResolve('override')} type="button">
          <strong>Replace conflicting event(s)</strong>
          <span>Remove the listed event(s) and schedule this event.</span>
        </button>
        <button disabled={disabled} onClick={() => onResolve('overlap')} type="button">
          <strong>Schedule both</strong>
          <span>Keep the existing event(s) and allow the overlap.</span>
        </button>
        <button disabled={disabled} onClick={() => onResolve('reject')} type="button">
          <strong>Cancel scheduling</strong>
          <span>Leave the calendar unchanged.</span>
        </button>
      </div>
    </div>
  )
}

function FilesPanel({ error, files, onDelete, onSearch, search }) {
  return (
    <main className="files-panel">
      <header className="files-header">
        <div>
          <span className="eyebrow">YOUR WORKSPACE</span>
          <h1>Files</h1>
          <p>Search your uploaded study material by meaning.</p>
        </div>
        <Icon name="folder" size={30} />
      </header>
      <label className="file-search">
        <Icon name="search" size={17} />
        <input
          aria-label="Search files semantically"
          onChange={(event) => onSearch(event.target.value)}
          placeholder="Search files semantically..."
          type="search"
          value={search}
        />
      </label>
      {error && <p className="file-error" role="alert">{error}</p>}
      <section className="file-list" aria-live="polite">
        {files.length === 0 ? (
          <p className="empty-files">
            {search ? 'No matching file excerpts found.' : 'Uploaded files will appear here.'}
          </p>
        ) : (
          files.map((file) => (
            <article className="file-card" key={`${file.id}-${file.chunk_index || 'document'}`}>
              <div className="file-card-icon"><Icon name="folder" size={18} /></div>
              <div className="file-card-body">
                <strong>{file.name}</strong>
                {file.content ? (
                  <p>{file.content.slice(0, 240)}{file.content.length > 240 ? '…' : ''}</p>
                ) : (
                  <p>{new Date(file.created_at).toLocaleString()}</p>
                )}
                {file.score !== undefined && (
                  <span className="file-score">Semantic match · {Math.round(file.score * 100)}%</span>
                )}
              </div>
              {!file.content && (
                <button
                  aria-label={`Delete ${file.name}`}
                  className="file-delete"
                  onClick={() => onDelete(file.id)}
                  type="button"
                >
                  Delete
                </button>
              )}
            </article>
          ))
        )}
      </section>
    </main>
  )
}

export default App
