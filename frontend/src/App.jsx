import { useEffect, useState } from 'react'

const API = 'http://localhost:8000'

const INTENTS = [
  { value: '', label: 'None' },
  { value: 'confess', label: 'Confess' },
  { value: 'deny', label: 'Deny / Lie' },
  { value: 'ask_favor', label: 'Ask Favor' },
  { value: 'gift_help', label: 'Gift / Help' },
  { value: 'threaten', label: 'Threaten' },
]

export default function App() {
  const [npc, setNpc] = useState('')
  const [player, setPlayer] = useState('')
  const [scene, setScene] = useState('tavern')
  const [intent, setIntent] = useState('')
  const [line, setLine] = useState('')
  const [facts, setFacts] = useState([])

  const [npcEntities, setNpcEntities] = useState([])
  const [playerEntities, setPlayerEntities] = useState([])
  const [loadingEntities, setLoadingEntities] = useState(true)
  const [entitiesError, setEntitiesError] = useState('')

  const [npcReply, setNpcReply] = useState('')

  // Load NPCs and Players from backend on mount
  useEffect(() => {
    const loadEntities = async () => {
      try {
        setLoadingEntities(true)
        const res = await fetch(`${API}/v0/entities`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        const npcs = data.filter((e) => e.kind === 'npc')
        const players = data.filter((e) => e.kind === 'player')

        setNpcEntities(npcs)
        setPlayerEntities(players)

        if (npcs.length > 0) setNpc(npcs[0].id)
        if (players.length > 0) setPlayer(players[0].id)
      } catch (err) {
        console.error(err)
        setEntitiesError('Failed to load entities')
      } finally {
        setLoadingEntities(false)
      }
    }

    loadEntities()
  }, [])

  const addFact = async () => {
    if (!line.trim() || !npc || !player) return

    await fetch(`${API}/v0/facts.add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        who: npc,
        about: player,
        scene,
        type: 'event',
        intent: intent || null,
        text: line,
        tags: intent ? [intent] : [],
        weight: 0.7,
      }),
    })

    setLine('')
  }

  const retrieve = async () => {
    if (!npc || !player) return

    const params = new URLSearchParams({
      npc_id: npc,
      player_id: player,
      scene,
    })
    if (intent) params.set('intent', intent)

    const res = await fetch(`${API}/v0/retrieve?` + params.toString())
    const data = await res.json()
    setFacts(data)
  }

  const togglePin = async (id, pinned) => {
    await fetch(`${API}/v0/pin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fact_id: id, pinned }),
    })
    retrieve()
  }

  const sendFeedback = async (id, reward) => {
    await fetch(`${API}/v0/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fact_id: id, reward }),
    })
    retrieve()
  }

  const generateFakeReply = () => {
    if (!facts.length) {
      setNpcReply('idk u well enough yet.')
      return
    }

    const top = facts[0]
    const tags = top.tags || []

    let reply = ''

    if (tags.includes('debt') || tags.includes('money')) {
      reply = 'you still owe me money. pay up before you ask for more.'
    } else if (tags.includes('favor') || tags.includes('gift_help')) {
      reply = 'i remember what you did for me. i can cut you some slack.'
    } else if (tags.includes('crime') || tags.includes('betrayal')) {
      reply = "i haven't forgotten what you did. i'm watching you."
    } else if (intent === 'confess') {
      reply = "fine. at least you're being honest about it this time."
    } else {
      reply = "alright. let's see what you want this time."
    }

    setNpcReply(reply)
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 16,
        padding: 24,
        fontFamily: 'system-ui',
      }}
    >
      <div>
        <h2>MemoryGraph Playground</h2>

        {loadingEntities && <div>Loading NPCs &amp; players...</div>}
        {entitiesError && (
          <div style={{ color: 'red', marginBottom: 8 }}>{entitiesError}</div>
        )}

        <div style={{ marginBottom: 8 }}>
          <label>
            NPC:&nbsp;
            <select
              value={npc}
              onChange={(e) => setNpc(e.target.value)}
              disabled={loadingEntities || npcEntities.length === 0}
            >
              {npcEntities.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.id}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ marginBottom: 8 }}>
          <label>
            Player:&nbsp;
            <select
              value={player}
              onChange={(e) => setPlayer(e.target.value)}
              disabled={loadingEntities || playerEntities.length === 0}
            >
              {playerEntities.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.id}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ marginBottom: 8 }}>
          <label>
            Scene:&nbsp;
            <input value={scene} onChange={(e) => setScene(e.target.value)} />
          </label>
        </div>

        <div style={{ marginBottom: 8 }}>
          <label>
            Intent:&nbsp;
            <select value={intent} onChange={(e) => setIntent(e.target.value)}>
              {INTENTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ marginTop: 12 }}>
          <textarea
            value={line}
            onChange={(e) => setLine(e.target.value)}
            placeholder="Player says or event text..."
            rows={4}
            style={{ width: '100%' }}
          />
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <button onClick={addFact} disabled={!npc || !player}>
            Add Fact
          </button>
          <button onClick={retrieve} disabled={!npc || !player}>
            Retrieve Top-K
          </button>
          <button onClick={generateFakeReply} disabled={!npc || !player}>
            Generate Fake Reply
          </button>
        </div>

        <p style={{ opacity: 0.7, marginTop: 8 }}>
          Tip: pick an NPC/player, choose Intent = Confess, type &quot;I still
          owe you that 10 gold&quot;, Add Fact, then Retrieve or Generate Fake
          Reply.
        </p>

        {npcReply && (
          <div
            style={{
              marginTop: 16,
              padding: 12,
              border: '1px solid #ccc',
              borderRadius: 8,
              background: '#f7f7f7',
            }}
          >
            <strong>npc reply:</strong>
            <p>{npcReply}</p>
          </div>
        )}
      </div>

      <div>
        <h2>Memory Inspector</h2>
        {!facts.length && <div>No facts yet. Click Retrieve.</div>}

        {facts.map((f) => (
          <div
            key={f.fact_id}
            style={{
              border: '1px solid #ccc',
              borderRadius: 8,
              padding: 12,
              marginBottom: 8,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <strong>{f.text}</strong>
              <span>score: {f.score}</span>
            </div>
            <div style={{ fontSize: 12, opacity: 0.8 }}>
              scene: {f.scene || '—'} | weight: {f.weight} | pinned:{' '}
              {String(f.pinned)} | intent: {f.intent || '—'}
            </div>
            <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>
              tags: {(f.tags || []).join(', ') || '—'}
            </div>
            <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
              {!f.pinned ? (
                <button onClick={() => togglePin(f.fact_id, true)}>Pin</button>
              ) : (
                <button onClick={() => togglePin(f.fact_id, false)}>
                  Unpin
                </button>
              )}
              <button onClick={() => sendFeedback(f.fact_id, 1)}>👍</button>
              <button onClick={() => sendFeedback(f.fact_id, -1)}>👎</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
