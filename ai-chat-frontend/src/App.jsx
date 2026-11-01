import { useState } from 'react'
import './App.css'

const tools = [
  { name: 'New chat', icon: 'plus' },
  { name: 'Explore', icon: 'search' },
  { name: 'Code assistant', icon: 'code' },
  { name: 'Projects', icon: 'folder' },
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

function App() {
  const [activeTool, setActiveTool] = useState('New chat')
  const [tasks, setTasks] = useState(initialTasks)
  const [prompt, setPrompt] = useState('')
  const [messages, setMessages] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [isSending, setIsSending] = useState(false)

  const completedTasks = tasks.filter((task) => task.completed).length

  function toggleTask(taskId) {
    setTasks((currentTasks) =>
      currentTasks.map((task) =>
        task.id === taskId ? { ...task, completed: !task.completed } : task,
      ),
    )
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
        body: JSON.stringify({ message, history }),
      })
      let result
      try {
        result = await response.json()
      } catch {
        throw new Error('The chat service returned an unreadable response. Please try again.')
      }

      if (!response.ok) {
        throw new Error(result.detail || 'The assistant could not complete your request.')
      }
      if (typeof result.reply !== 'string' || !result.reply.trim()) {
        throw new Error('The assistant returned an empty reply. Please try again.')
      }

      setMessages((currentMessages) => [
        ...currentMessages,
        { role: 'assistant', content: result.reply },
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
          <button className="profile-button" type="button" aria-label="User profile">
            <span className="avatar">H</span>
            <span className="profile-name">Huy Le</span>
            <span className="profile-plan">Personal</span>
          </button>
        </div>
      </aside>

      <main className="chat-panel">
        <header className="topbar">
          <span className="topbar-message">message for checking in</span>
          <button className="mobile-profile" type="button" aria-label="User profile">
            H
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
              {messages.map((message, index) => (
                <p
                  className={`chat-message ${message.role}-message`}
                  key={`${index}-${message.role}`}
                >
                  {message.content}
                </p>
              ))}
              {isSending && <p className="assistant-message typing-indicator">Thinking...</p>}
            </div>
          )}

          <div className="composer-wrap">
            <form className="composer" onSubmit={submitPrompt}>
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
                <span className="composer-hint">Shift + Enter for a new line</span>
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
          </div>
        </section>
      </main>

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

export default App
