import { useEffect, useState } from 'react'

const API = 'http://localhost:8000'

export default function App() {
  const [health, setHealth] = useState('checking...')
  const [error, setError] = useState('')

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`${API}/v0/health`)
        if (!res.ok) throw new Error(`http ${res.status}`)
        const data = await res.json()
        setHealth(JSON.stringify(data))
      } catch (err) {
        console.error(err)
        setError('api not responding')
      }
    }

    check()
  }, [])

  return (
    <div
      style={{
        padding: 24,
        fontFamily: 'system-ui',
        color: 'white',
        background: '#1e1e1e',
        minHeight: '100vh',
      }}
    >
      <h1>memorygraph dev</h1>
      <p>backend health: {health}</p>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      <p style={{ marginTop: 16, opacity: 0.7 }}>
        this is just the starter wire. once this works, we plug in the npc
        memory stuff.
      </p>
    </div>
  )
}
