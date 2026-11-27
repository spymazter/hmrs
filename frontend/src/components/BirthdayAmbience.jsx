const SPRINKLE_COLORS = ['#f43f5e', '#f59e0b', '#22c55e', '#3b82f6', '#a855f7', '#ec4899']

export function isBirthdayToday(dob) {
  if (!dob) return false
  const born = new Date(`${dob}T00:00:00`)
  if (Number.isNaN(born.getTime())) return false
  const today = new Date()
  return born.getMonth() === today.getMonth() && born.getDate() === today.getDate()
}

export default function BirthdayAmbience({ subtle = false }) {
  const balloonCount = subtle ? 6 : 9
  const sprinkleCount = subtle ? 22 : 34

  return (
    <div className={`birthday-ambience${subtle ? ' subtle' : ''}`} aria-hidden="true">
      <div className="birthday-ambience-balloons">
        {Array.from({ length: balloonCount }, (_, index) => (
          <span
            key={index}
            style={{
              left: `${4 + (index * 92) / Math.max(balloonCount - 1, 1)}%`,
              animationDelay: `${index * 0.9}s`,
              animationDuration: `${9 + (index % 3) * 2}s`,
            }}
          >
            🎈
          </span>
        ))}
      </div>
      <div className="birthday-ambience-sprinkles">
        {Array.from({ length: sprinkleCount }, (_, index) => (
          <span
            key={index}
            style={{
              left: `${(index * 41) % 100}%`,
              background: SPRINKLE_COLORS[index % SPRINKLE_COLORS.length],
              animationDelay: `${(index % 10) * 0.6}s`,
              animationDuration: `${4.5 + (index % 4) * 0.8}s`,
            }}
          />
        ))}
      </div>
    </div>
  )
}
