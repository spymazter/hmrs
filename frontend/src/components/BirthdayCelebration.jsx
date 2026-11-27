import { useEffect, useState } from 'react'
import api from '../api'
import { useAuth } from '../context/AuthContext'

const BALLOONS = ['🎈', '🎈', '🎈', '🎈', '🎈', '🎈', '🎈', '🎈']
const SPRINKLE_COLORS = ['#f43f5e', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#ec4899']
const SPRINKLES = Array.from({ length: 46 }, (_, index) => ({
  left: `${(index * 37) % 100}%`,
  delay: `${(index % 12) * 0.42}s`,
  duration: `${3.2 + (index % 5) * 0.5}s`,
  color: SPRINKLE_COLORS[index % SPRINKLE_COLORS.length],
}))

export default function BirthdayCelebration() {
  const { user } = useAuth()
  const [profile, setProfile] = useState(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    if (!user?.employee_id) return
    api.get('/employees/me').then((res) => setProfile(res.data)).catch(() => {})
  }, [user?.employee_id])

  const dob = profile?.date_of_birth
  if (!dob || dismissed || !user?.employee_id) return null

  const today = new Date()
  const born = new Date(`${dob}T00:00:00`)
  if (born.getMonth() !== today.getMonth() || born.getDate() !== today.getDate()) return null

  const key = `hrms_birthday_${today.getFullYear()}_${today.getMonth() + 1}_${today.getDate()}_${user.id}`
  if (sessionStorage.getItem(key)) return null

  const close = () => {
    sessionStorage.setItem(key, '1')
    setDismissed(true)
  }
  const firstName = (profile.first_name || user.full_name || 'there').split(' ')[0]

  return (
    <div className="birthday-celebration" role="dialog" aria-label="Happy birthday">
      <div className="birthday-sprinklers" aria-hidden="true">
        {SPRINKLES.map((sprinkle, index) => (
          <span
            key={index}
            style={{
              left: sprinkle.left,
              background: sprinkle.color,
              animationDelay: sprinkle.delay,
              animationDuration: sprinkle.duration,
            }}
          />
        ))}
      </div>

      <div className="birthday-balloons" aria-hidden="true">
        {BALLOONS.map((balloon, index) => (
          <span key={index} style={{ left: `${6 + index * 12}%`, animationDelay: `${index * 0.65}s` }}>
            {balloon}
          </span>
        ))}
      </div>

      <div className="birthday-card">
        <div className="birthday-cake" aria-hidden="true">
          <div className="birthday-flames"><i /><i /><i /></div>
          <div className="birthday-candles"><i /><i /><i /></div>
          <div className="birthday-cake-body">🎂</div>
        </div>
        <div className="birthday-kicker">It's your day</div>
        <h1>Happy Birthday, {firstName}!</h1>
        <p>May your day be filled with joy, laughter and cake.</p>
        <button className="btn btn-primary" onClick={close}>Celebrate 🎉</button>
      </div>
    </div>
  )
}
