import { useCallback, useEffect, useState } from 'react'
import './Calendar.css'

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function toDateKey(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function parseDateKey(value) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function formatEventTime(event) {
  const [hour, minute] = event.time.split(':').map(Number)
  const totalEndMinutes = hour * 60 + minute + event.duration_minutes
  const endMinutes = totalEndMinutes % (24 * 60)
  const dayOffset = Math.floor(totalEndMinutes / (24 * 60))
  const endTime = `${String(Math.floor(endMinutes / 60)).padStart(2, '0')}:${String(endMinutes % 60).padStart(2, '0')}`
  return `${event.time}–${endTime}${dayOffset ? ` (+${dayOffset}d)` : ''}`
}

function weekdayForDate(date) {
  return (parseDateKey(date).getDay() + 6) % 7
}

function CalendarView({ onUnauthorized }) {
  const [today] = useState(() => new Date())
  const [events, setEvents] = useState(null)
  const [reloadVersion, setReloadVersion] = useState(0)
  const [visibleMonth, setVisibleMonth] = useState(
    () => new Date(today.getFullYear(), today.getMonth(), 1),
  )
  const [selectedDate, setSelectedDate] = useState(() => toDateKey(today))
  const [view, setView] = useState('month')
  const [draft, setDraft] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [actionError, setActionError] = useState('')
  const [pendingConflict, setPendingConflict] = useState(null)
  const [resolvingConflict, setResolvingConflict] = useState(false)

  const reloadEvents = useCallback(() => {
    setReloadVersion((version) => version + 1)
  }, [])

  useEffect(() => {
    let active = true
    async function loadEvents() {
      try {
        const requestThrough = new Date(
          visibleMonth.getFullYear(),
          visibleMonth.getMonth() + 2,
          0,
        )
        const response = await fetch(
          `/api/calendar/events?date_to=${toDateKey(requestThrough)}`,
        )
        const result = await response.json()
        if (!active) return
        if (response.status === 401) {
          onUnauthorized(result.detail || 'Your session expired. Please sign in again.')
          return
        }
        if (!response.ok) {
          throw new Error(result.detail || 'Unable to load calendar events.')
        }
        setEvents(result.events)
        setLoadError('')
      } catch (error) {
        if (!active) return
        setLoadError(error instanceof Error ? error.message : 'Unable to load calendar events.')
        setEvents((currentEvents) => currentEvents ?? [])
      }
    }
    loadEvents()
    return () => {
      active = false
    }
  }, [onUnauthorized, reloadVersion, visibleMonth])

  const monthTitle = new Intl.DateTimeFormat(undefined, {
    month: 'long',
    year: 'numeric',
  }).format(visibleMonth)

  function chooseDate(date) {
    setSelectedDate(toDateKey(date))
    setVisibleMonth(new Date(date.getFullYear(), date.getMonth(), 1))
  }

  function moveCalendar(direction) {
    if (view === 'week') {
      const nextDate = parseDateKey(selectedDate)
      nextDate.setDate(nextDate.getDate() + direction * 7)
      chooseDate(nextDate)
      return
    }

    setVisibleMonth(
      (current) => new Date(current.getFullYear(), current.getMonth() + direction, 1),
    )
    if (view === 'agenda') {
      setSelectedDate((current) => {
        const nextDate = parseDateKey(current)
        nextDate.setMonth(nextDate.getMonth() + direction)
        return toDateKey(nextDate)
      })
    }
  }

  function openNewEvent(date = selectedDate) {
    setEditingId(null)
    setDraft({
      title: '',
      date,
      time: '',
      duration_minutes: 15,
      type: 'appointment',
      notes: '',
      recurrence: null,
      recurrence_scope: 'this_occurrence',
    })
  }

  function openEvent(event) {
    setEditingId(event.id)
    setDraft({
      ...event,
      selected_occurrence_date: event.date,
      recurrence_scope: 'this_occurrence',
    })
  }

  function closeEditor() {
    setDraft(null)
    setEditingId(null)
    setActionError('')
  }

  async function saveEvent(event) {
    event.preventDefault()
    setActionError('')
    const body = {
      title: draft.title.trim(),
      date: draft.date,
      time: draft.time,
      duration_minutes: Number(draft.duration_minutes),
      type: draft.type,
      notes: draft.notes.trim(),
      recurrence:
        draft.series_id && draft.recurrence_scope === 'this_occurrence'
          ? null
          : draft.recurrence,
    }
    const scope = draft.series_id ? draft.recurrence_scope : 'this_occurrence'
    try {
      const response = await fetch(
        editingId
          ? `/api/calendar/events/${editingId}?scope=${scope}`
          : '/api/calendar/events',
        {
          method: editingId ? 'PUT' : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      )
      const result = await response.json()
      if (response.status === 409 && result.detail?.proposal_id) {
        setPendingConflict(result.detail)
        closeEditor()
        return
      }
      if (response.status === 401) {
        onUnauthorized(result.detail || 'Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to save this event.')
      }
      chooseDate(parseDateKey(result.event.date))
      closeEditor()
      await reloadEvents()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to save this event.')
    }
  }

  async function deleteEvent() {
    setActionError('')
    try {
      const scope = draft.series_id ? draft.recurrence_scope : 'this_occurrence'
      const response = await fetch(
        `/api/calendar/events/${editingId}?scope=${scope}`,
        { method: 'DELETE' },
      )
      const result = await response.json()
      if (response.status === 401) {
        onUnauthorized(result.detail || 'Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to delete this event.')
      }
      closeEditor()
      await reloadEvents()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to delete this event.')
    }
  }

  async function setEventCompleted(eventId, completed) {
    setActionError('')
    try {
      const response = await fetch(`/api/calendar/events/${eventId}/completion`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ completed }),
      })
      const result = await response.json()
      if (response.status === 401) {
        onUnauthorized(result.detail || 'Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to update event status.')
      }
      if (draft?.id === eventId) {
        setDraft((current) => ({ ...current, completed: result.event.completed }))
      }
      await reloadEvents()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to update event status.')
    }
  }

  async function resolveEventConflict(resolution) {
    if (!pendingConflict) return
    setResolvingConflict(true)
    setActionError('')
    try {
      const response = await fetch(
        `/api/calendar/proposals/${pendingConflict.proposal_id}/resolve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ resolution }),
        },
      )
      const result = await response.json()
      if (response.status === 409 && result.detail?.status === 'conflict') {
        setPendingConflict(result.detail)
        return
      }
      if (response.status === 401) {
        onUnauthorized(result.detail || 'Your session expired. Please sign in again.')
        return
      }
      if (!response.ok) {
        throw new Error(result.detail || 'Unable to resolve this conflict.')
      }
      setPendingConflict(null)
      await reloadEvents()
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Unable to resolve this conflict.')
    } finally {
      setResolvingConflict(false)
    }
  }

  const monthStart = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1)
  const daysInMonth = [
    31,
    visibleMonth.getFullYear() % 4 === 0 &&
    (visibleMonth.getFullYear() % 100 !== 0 || visibleMonth.getFullYear() % 400 === 0)
      ? 29
      : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ][visibleMonth.getMonth()]
  const firstGridDate = new Date(monthStart)
  firstGridDate.setDate(firstGridDate.getDate() - firstGridDate.getDay())
  const monthWeekCount = Math.ceil((monthStart.getDay() + daysInMonth) / 7)
  const monthDates = Array.from({ length: monthWeekCount * 7 }, (_, index) => {
    const date = new Date(firstGridDate)
    date.setDate(firstGridDate.getDate() + index)
    return date
  })

  const weekStart = parseDateKey(selectedDate)
  weekStart.setDate(weekStart.getDate() - weekStart.getDay())
  const weekDates = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(weekStart)
    date.setDate(weekStart.getDate() + index)
    return date
  })

  function eventsOn(date) {
    return (events || [])
      .filter((event) => event.date === toDateKey(date))
      .sort((first, second) => first.time.localeCompare(second.time))
  }

  const agendaEvents = (events || [])
    .filter((event) => {
      const date = parseDateKey(event.date)
      return (
        date.getFullYear() === visibleMonth.getFullYear() &&
        date.getMonth() === visibleMonth.getMonth()
      )
    })
    .sort((first, second) =>
      first.date === second.date
        ? first.time.localeCompare(second.time)
        : first.date.localeCompare(second.date),
    )

  return (
    <section className="calendar-view" aria-label="Calendar">
      <header className="calendar-toolbar">
        <div className="calendar-navigation">
          <button
            className="calendar-today"
            onClick={() => chooseDate(new Date())}
            type="button"
          >
            Today
          </button>
          <div className="calendar-arrows">
            <button
              aria-label="Previous"
              onClick={() => moveCalendar(-1)}
              type="button"
            >
              <CalendarIcon name="left" />
            </button>
            <button
              aria-label="Next"
              onClick={() => moveCalendar(1)}
              type="button"
            >
              <CalendarIcon name="right" />
            </button>
          </div>
          <h1>{monthTitle}</h1>
        </div>

        <div className="calendar-toolbar-actions">
          <div className="calendar-view-switch" aria-label="Calendar view">
            {['week', 'month', 'agenda'].map((option) => (
              <button
                aria-pressed={view === option}
                className={view === option ? 'selected' : ''}
                key={option}
                onClick={() => setView(option)}
                type="button"
              >
                {option[0].toUpperCase() + option.slice(1)}
              </button>
            ))}
          </div>
          <button
            aria-label="Create event"
            className="calendar-add"
            onClick={() => openNewEvent()}
            type="button"
          >
            <CalendarIcon name="plus" />
          </button>
        </div>
      </header>

      {(loadError || (actionError && !draft && !pendingConflict)) && (
        <p className="calendar-storage-error" role="alert">{loadError || actionError}</p>
      )}

      {events === null ? (
        <div className="calendar-loading" role="status">Loading your calendar...</div>
      ) : view === 'agenda' ? (
        <div className="agenda-view">
          {agendaEvents.length ? (
            agendaEvents.map((event) => (
              <button
                className={`agenda-event ${event.type} ${event.completed ? 'completed' : ''}`}
                key={event.id}
                onClick={() => openEvent(event)}
                type="button"
              >
                <span className="agenda-date">
                  <strong>{parseDateKey(event.date).getDate()}</strong>
                  <span>{new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(parseDateKey(event.date))}</span>
                </span>
                <span className="agenda-event-copy">
                  <strong>{event.title}</strong>
                  <span>{event.time ? formatEventTime(event) : event.type}</span>
                  {event.recurrence && <span>Repeats {event.recurrence.frequency}</span>}
                  {event.notes && <span>{event.notes}</span>}
                </span>
              </button>
            ))
          ) : (
            <div className="calendar-empty">
              <span className="calendar-empty-icon"><CalendarIcon name="calendar" /></span>
              <strong>No events this month</strong>
              <span>Add an appointment or reminder to get started.</span>
              <button className="calendar-inline-add" onClick={() => openNewEvent()} type="button">
                Create an event
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className={`calendar-grid ${view === 'week' ? 'week-grid' : 'month-grid'}`}>
          <div className="weekday-row" aria-hidden="true">
            {WEEKDAYS.map((day) => <span key={day}>{day}</span>)}
          </div>
          <div
            className="calendar-days"
            style={{ '--month-week-count': monthWeekCount }}
          >
            {(view === 'week' ? weekDates : monthDates).map((date) => {
              const dateKey = toDateKey(date)
              const dayEvents = eventsOn(date)
              const isToday = dateKey === toDateKey(today)
              const isSelected = dateKey === selectedDate
              const isCurrentMonth = date.getMonth() === visibleMonth.getMonth()

              return (
                <div
                  className={[
                    'calendar-day',
                    !isCurrentMonth && view === 'month' ? 'outside-month' : '',
                    isToday ? 'today' : '',
                    isSelected ? 'selected-day' : '',
                  ].filter(Boolean).join(' ')}
                  key={dateKey}
                >
                  <div className="calendar-day-heading">
                    <button
                      aria-label={`Select ${new Intl.DateTimeFormat(undefined, {
                        dateStyle: 'full',
                      }).format(date)}`}
                      className="calendar-day-number"
                      onClick={() => chooseDate(date)}
                      type="button"
                    >
                      {date.getDate()}
                    </button>
                    <button
                      aria-label={`Add event on ${dateKey}`}
                      className="calendar-day-add"
                      onClick={() => openNewEvent(dateKey)}
                      type="button"
                    >
                      <CalendarIcon name="plus" />
                    </button>
                  </div>
                  <div className="calendar-day-events">
                    {dayEvents.slice(0, view === 'week' ? 8 : 3).map((event) => (
                      <button
                        className={`calendar-event ${event.type} ${event.completed ? 'completed' : ''}`}
                        key={event.id}
                        onClick={() => openEvent(event)}
                        title={`${event.time ? `${formatEventTime(event)} · ` : ''}${event.title}${event.recurrence ? ` · Repeats ${event.recurrence.frequency}` : ''}`}
                        type="button"
                      >
                        {event.time && <time>{formatEventTime(event)}</time>}
                        <span>{event.title}</span>
                      </button>
                    ))}
                    {dayEvents.length > (view === 'week' ? 8 : 3) && (
                      <button
                        className="calendar-more-events"
                        onClick={() => {
                          chooseDate(date)
                          setView('agenda')
                        }}
                        type="button"
                      >
                        +{dayEvents.length - (view === 'week' ? 8 : 3)} more
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {draft && (
        <div
          className="calendar-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeEditor()
          }}
        >
          <section
            aria-labelledby="event-dialog-title"
            aria-modal="true"
            className="event-dialog"
            role="dialog"
          >
            <header className="event-dialog-header">
              <div>
                <span className="eyebrow">CALENDAR</span>
                <h2 id="event-dialog-title">{editingId ? 'Edit event' : 'Create an event'}</h2>
              </div>
              <button aria-label="Close" className="dialog-close" onClick={closeEditor} type="button">
                <CalendarIcon name="close" />
              </button>
            </header>
            <form className="event-form" onSubmit={saveEvent}>
              {actionError && <p className="calendar-storage-error" role="alert">{actionError}</p>}
              <label>
                Title
                <input
                  autoFocus
                  maxLength={100}
                  onChange={(event) => setDraft({ ...draft, title: event.target.value })}
                  placeholder="What are you planning?"
                  required
                  value={draft.title}
                />
              </label>
              <div className="event-form-row">
                <label>
                  Date
                  <input
                    onChange={(event) => setDraft({ ...draft, date: event.target.value })}
                    required
                    type="date"
                    value={draft.date}
                  />
                </label>
                <label>
                  Time
                  <input
                    onChange={(event) => setDraft({ ...draft, time: event.target.value })}
                    required
                    step={900}
                    type="time"
                    value={draft.time}
                  />
                </label>
              </div>
              <label>
                Duration (minutes)
                <input
                  max={1440}
                  min={15}
                  onChange={(event) => setDraft({
                    ...draft,
                    duration_minutes: event.target.value,
                  })}
                  required
                  step={15}
                  type="number"
                  value={draft.duration_minutes}
                />
              </label>
              {draft.series_id && (
                <label>
                  Apply changes to
                  <select
                    onChange={(event) => {
                      const scope = event.target.value
                      const date = scope === 'series'
                        ? draft.series_start_date
                        : scope === 'following'
                          ? draft.occurrence_date
                          : draft.selected_occurrence_date
                      setDraft({ ...draft, recurrence_scope: scope, date })
                    }}
                    value={draft.recurrence_scope}
                  >
                    <option value="this_occurrence">This occurrence</option>
                    <option value="following">This and following</option>
                    <option value="series">Entire series</option>
                  </select>
                </label>
              )}
              {(!editingId || (draft.series_id && draft.recurrence_scope !== 'this_occurrence')) && (
                <>
                  <label>
                    Repeat
                    <select
                      onChange={(event) => {
                        const frequency = event.target.value
                        setDraft({
                          ...draft,
                          recurrence: frequency
                            ? {
                                frequency,
                                interval: 1,
                                weekdays: frequency === 'weekly'
                                  ? [weekdayForDate(draft.date)]
                                  : [],
                              }
                            : null,
                        })
                      }}
                      value={draft.recurrence?.frequency || ''}
                    >
                      {!draft.series_id && <option value="">Does not repeat</option>}
                      <option value="daily">Daily</option>
                      <option value="weekly">Weekly</option>
                      <option value="monthly">Monthly</option>
                      <option value="yearly">Yearly</option>
                    </select>
                  </label>
                  {draft.recurrence && (
                    <>
                      <label>
                        Repeat every
                        <div className="recurrence-interval">
                          <input
                            max={52}
                            min={1}
                            onChange={(event) => setDraft({
                              ...draft,
                              recurrence: {
                                ...draft.recurrence,
                                interval: Number(event.target.value),
                              },
                            })}
                            type="number"
                            value={draft.recurrence.interval}
                          />
                          <span>
                            {draft.recurrence.frequency === 'daily' ? 'day(s)'
                              : draft.recurrence.frequency === 'weekly' ? 'week(s)'
                                : draft.recurrence.frequency === 'monthly' ? 'month(s)'
                                  : 'year(s)'}
                          </span>
                        </div>
                      </label>
                      {draft.recurrence.frequency === 'weekly' && (
                        <fieldset className="recurrence-weekdays">
                          <legend>Repeat on</legend>
                          {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day, index) => (
                            <label key={day}>
                              <input
                                checked={draft.recurrence.weekdays.includes(index)}
                                onChange={(event) => {
                                  const weekdays = event.target.checked
                                    ? [...draft.recurrence.weekdays, index].sort()
                                    : draft.recurrence.weekdays.filter((weekday) => weekday !== index)
                                  setDraft({
                                    ...draft,
                                    recurrence: { ...draft.recurrence, weekdays },
                                  })
                                }}
                                type="checkbox"
                              />
                              {day}
                            </label>
                          ))}
                        </fieldset>
                      )}
                    </>
                  )}
                </>
              )}
              <label>
                Type
                <select
                  onChange={(event) => setDraft({ ...draft, type: event.target.value })}
                  value={draft.type}
                >
                  <option value="appointment">Appointment</option>
                  <option value="reminder">Reminder</option>
                </select>
              </label>
              {editingId && (
                <label className="event-completion">
                  <input
                    checked={Boolean(draft.completed)}
                    onChange={(event) => setEventCompleted(editingId, event.target.checked)}
                    type="checkbox"
                  />
                  Mark this event as done
                </label>
              )}
              <label>
                Notes <span className="optional-label">Optional</span>
                <textarea
                  maxLength={500}
                  onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
                  placeholder="Add details"
                  rows={3}
                  value={draft.notes}
                />
              </label>
              <footer className="event-form-actions">
                {editingId && (
                  <button className="event-delete" onClick={deleteEvent} type="button">
                    Delete
                  </button>
                )}
                <span />
                <button className="event-cancel" onClick={closeEditor} type="button">Cancel</button>
                <button className="event-save" type="submit">
                  {editingId ? 'Save changes' : 'Create event'}
                </button>
              </footer>
            </form>
          </section>
        </div>
      )}

      {pendingConflict && (
        <div className="calendar-dialog-backdrop">
          <section
            aria-labelledby="calendar-conflict-title"
            aria-modal="true"
            className="event-dialog conflict-dialog"
            role="dialog"
          >
            <header className="event-dialog-header">
              <div>
                <span className="eyebrow">TIME SLOT CONFLICT</span>
                <h2 id="calendar-conflict-title">Choose how to resolve it</h2>
              </div>
              <button
                aria-label="Close"
                className="dialog-close"
                onClick={() => resolveEventConflict('reject')}
                type="button"
                disabled={resolvingConflict}
              >
                <CalendarIcon name="close" />
              </button>
            </header>
            <p className="conflict-dialog-copy">
              <strong>Nothing has been changed.</strong>{' '}
              <strong>{pendingConflict.event?.title || pendingConflict.title}</strong>
              {' '}at {formatEventTime(pendingConflict.event || pendingConflict)}
              {' '}on {pendingConflict.event?.date || pendingConflict.date}
              {pendingConflict.occurrence_count > 1
                ? ` repeats for ${pendingConflict.occurrence_count} occurrences and`
                : ''}{' '}conflicts with {pendingConflict.conflict_count || pendingConflict.conflicts?.length || 0}
              {' '}event(s). Your choice will apply to all conflicts
              {pendingConflict.conflict_count > (pendingConflict.conflicts?.length || 0)
                ? `; showing the first ${pendingConflict.conflicts?.length || 0}`
                : ''}.
            </p>
            <ul className="conflict-event-list">
              {(pendingConflict.conflicts || []).map((event) => (
                <li key={event.id}>
                  <strong>{event.title}</strong>
                  <span>{event.date} · {event.duration_minutes
                    ? formatEventTime(event)
                    : event.time}</span>
                </li>
              ))}
            </ul>
            {actionError && <p className="calendar-storage-error" role="alert">{actionError}</p>}
            <div className="conflict-resolution-options">
              <button
                disabled={resolvingConflict}
                onClick={() => resolveEventConflict('override')}
                type="button"
              >
                <strong>Replace conflicting event(s)</strong>
                <span>Remove conflicting event(s) and add this event.</span>
              </button>
              <button
                disabled={resolvingConflict}
                onClick={() => resolveEventConflict('overlap')}
                type="button"
              >
                <strong>Schedule both</strong>
                <span>Keep existing events and add this event too.</span>
              </button>
              <button
                disabled={resolvingConflict}
                onClick={() => resolveEventConflict('reject')}
                type="button"
              >
                <strong>Cancel scheduling</strong>
                <span>Leave the calendar unchanged.</span>
              </button>
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

function CalendarIcon({ name }) {
  const paths = {
    calendar: (
      <>
        <rect x="3.5" y="5" width="17" height="16" rx="2" />
        <path d="M16 3v4M8 3v4M3.5 10h17" />
      </>
    ),
    close: <path d="m6 6 12 12M18 6 6 18" />,
    left: <path d="m15 18-6-6 6-6" />,
    plus: <path d="M12 5v14M5 12h14" />,
    right: <path d="m9 18 6-6-6-6" />,
  }

  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="18"
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.7"
      viewBox="0 0 24 24"
      width="18"
    >
      {paths[name]}
    </svg>
  )
}

export default CalendarView
