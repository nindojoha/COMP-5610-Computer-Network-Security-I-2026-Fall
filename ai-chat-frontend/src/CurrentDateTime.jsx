import { useEffect, useState } from 'react'
import { toLocalDateTime } from './localDateTime.js'

const localDateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  weekday: 'short',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  timeZoneName: 'short',
})

function CurrentDateTime() {
  const [currentDateTime, setCurrentDateTime] = useState(() => new Date())

  useEffect(() => {
    const timerId = window.setInterval(() => setCurrentDateTime(new Date()), 1000)
    return () => window.clearInterval(timerId)
  }, [])

  return (
    <time
      className="current-datetime"
      dateTime={toLocalDateTime(currentDateTime)}
      title="Your local date and time is included with chat requests for relative dates."
    >
      {localDateTimeFormatter.format(currentDateTime)}
    </time>
  )
}

export default CurrentDateTime
