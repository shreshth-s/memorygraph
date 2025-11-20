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

  const [conversationId, setConversationId] = useState('')
  const [convStatus, setConvStatus] = useState('idle')

  const [reply, setReply] = useState('')
  const [replying, setReplying] = useState(false)
  // New state for LLM loading status
  const [llmReplying, setLlmReplying] = useState(false)

  const [msg, setMsg] = useState('')
  const [showDebug, setShowDebug] = useState(false)

  useEffect(() => {
    const loadEntities = async () => {
      try {
        setLoadingEntities(true)
        const res = await fetch(`${API}/v0/entities`)
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        const npcs = data.filter(e => e.kind === 'npc')
        const players = data.filter(e => e.kind === 'player')
        setNpcEntities(npcs)
        setPlayerEntities(players)
        if (npcs.length > 0) setNpc(npcs[0].id)
        if (players.length > 0) setPlayer(players[0].id)
      } catch {
        setEntitiesError('Failed to load entities')
      } finally {
        setLoadingEntities(false)
      }
    }
    loadEntities()
  }, [])

  const startConversation = async () => {
    if (!npc || !player) return
    setConvStatus('starting')
    const res = await fetch(`${API}/v0/conversations.start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ npc_id: npc, player_id: player, scene })
    })
    const data = await res.json()
    setConversationId(data.conversation_id || '')
    setConvStatus(data.conversation_id ? 'active' : 'idle')
  }

  const resetConversation = () => {
    setConversationId('')
    setConvStatus('idle')
  }

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
        tags: intent ? [intent] : []
      }),
    })
    setLine('')
  }

  const retrieve = async () => {
    if (!npc || !player) return
    const params = new URLSearchParams({ npc_id: npc, player_id: player, scene })
    if (intent) params.set('intent', intent)
    if (conversationId) params.set('conversation_id', conversationId)
    const res = await fetch(`${API}/v0/retrieve?` + params.toString())
    const data = await res.json()
    setFacts(data)
    if (conversationId && data.length) {
      await fetch(`${API}/v0/conversations.attach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: conversationId, fact_ids: data.map(f => f.fact_id) })
      })
    }
  }

  const togglePin = async (id, pinned) => {
    await fetch(`${API}/v0/pin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fact_id: id, pinned }),
    })
    retrieve()
  }

  const sendFeedback = async (id, reward, oldWeight) => {
    const res = await fetch(`${API}/v0/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fact_id: id, reward })
    })
    const data = await res.json().catch(() => ({}))
    const newW = data?.weight ?? null
    if (typeof newW === 'number') {
      setMsg(`weight: ${Number(oldWeight).toFixed(2)} → ${Number(newW).toFixed(2)}`)
    } else {
      setMsg(reward > 0 ? '👍 recorded' : '👎 recorded')
    }
    setTimeout(() => setMsg(''), 1500)
    retrieve()
  }

  const generateFakeReply = async () => {
    if (!npc || !player) return
    setReplying(true)
    try {
      // ensure a conversation exists, so attachments/tags accumulate
      if (!conversationId) {
        await startConversation()
      }
      const body = {
        npc_id: npc,
        player_id: player,
        scene,
        conversation_id: conversationId || undefined,
        user_text: line || '',    // optional; gives flavor to templates
        intent: intent || undefined
      }
      const res = await fetch(`${API}/v0/reply.fake`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if (!res.ok) {
        setMsg(`fake reply failed: HTTP ${res.status}`)
        setTimeout(() => setMsg(''), 2000)
        return
      }
      const data = await res.json()
      setReply(data?.reply || '(no reply)')
      // sync inspector for visibility
      retrieve()
    } catch (e) {
      console.error(e)
      setMsg('fake reply error (see console)')
      setTimeout(() => setMsg(''), 2000)
    } finally {
      setReplying(false)
    }
  }

  // --- New function for real LLM Reply ---
  const generateLLMReply = async () => {
    if (!npc || !player || !line.trim()) {
      setMsg('Player line is required for LLM reply')
      setTimeout(() => setMsg(''), 2000)
      return
    }
    setLlmReplying(true)
    setReply('') // Clear old reply
    try {
      // ensure a conversation exists
      if (!conversationId) {
        await startConversation()
      }
      const body = {
        npc_id: npc,
        player_id: player,
        scene,
        conversation_id: conversationId || undefined,
        user_text: line || '', // required for this endpoint
        intent: intent || undefined
      }
      const res = await fetch(`${API}/v0/reply`, { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setMsg(`LLM reply failed: ${err.detail || `HTTP ${res.status}`}`)
        setTimeout(() => setMsg(''), 3000)
        return
      }
      const data = await res.json()
      setReply(data?.reply || '(no reply)')
      // sync inspector for visibility
      retrieve()
    } catch (e) {
      console.error(e)
      setMsg('LLM reply error (see console)')
      setTimeout(() => setMsg(''), 2000)
    } finally {
      setLlmReplying(false)
    }
  }

  const exportAll = async () => {
    const res = await fetch(`${API}/v0/export`)
    const data = await res.json()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'memorygraph-export.json'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const importAll = async (file) => {
    if (!file) return
    const text = await file.text()
    const payload = JSON.parse(text)
    const res = await fetch(`${API}/v0/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    if (res.ok) {
      setMsg('Imported. Reloading entities…')
      const ents = await fetch(`${API}/v0/entities`).then(r => r.json())
      const npcs = ents.filter(e => e.kind === 'npc')
      const players = ents.filter(e => e.kind === 'player')
      setNpcEntities(npcs); setPlayerEntities(players)
      setMsg('')
    } else {
      setMsg('Import failed')
      setTimeout(() => setMsg(''), 1500)
    }
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

        {msg && (
          <div style={{ marginBottom: 8, padding: 8, border: '1px solid #ddd', borderRadius: 6 }}>
            {msg}
          </div>
        )}

        {loadingEntities && <div>Loading NPCs &amp; players...</div>}
        {entitiesError && (
          <div style={{ color: 'red', marginBottom: 8 }}>{entitiesError}</div>
        )}

        <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
          <label>
            NPC:&nbsp;
            <select
              value={npc}
              onChange={(e) => setNpc(e.target.value)}
              disabled={loadingEntities || npcEntities.length === 0 || convStatus === 'active'}
            >
              {npcEntities.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.id}
                </option>
              ))}
            </select>
          </label>

          <label>
            Player:&nbsp;
            <select
              value={player}
              onChange={(e) => setPlayer(e.target.value)}
              disabled={loadingEntities || playerEntities.length === 0 || convStatus === 'active'}
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
            <input
              value={scene}
              onChange={(e) => setScene(e.target.value)}
              disabled={convStatus === 'active'}
            />
          </label>
        </div>

        <div style={{ marginBottom: 8 }}>
          <label>
            Intent:&nbsp;
            <select
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
            >
              {INTENTS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div style={{ marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {conversationId ? (
            <>
              <button disabled>Conversation: {conversationId.slice(0, 8)}…</button>
              <button onClick={resetConversation}>New Conversation</button>
            </>
          ) : (
            <button onClick={startConversation} disabled={!npc || !player || convStatus === 'starting'}>
              {convStatus === 'starting' ? 'Starting…' : 'Start Conversation'}
            </button>
          )}
          <label style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input
              type="checkbox"
              checked={showDebug}
              onChange={(e) => setShowDebug(e.target.checked)}
            />
            <span>Show score breakdown</span>
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

        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
          <button onClick={addFact} disabled={!npc || !player}>Add Fact</button>
          <button onClick={retrieve} disabled={!npc || !player}>Retrieve Top-K</button>
          
          {/* Fake Reply Button */}
          <button onClick={generateFakeReply} disabled={!npc || !player || replying || llmReplying}>
            {replying ? 'Thinking…' : 'Generate Fake Reply'}
          </button>

          {/* Real LLM Reply Button */}
          <button onClick={generateLLMReply} disabled={!npc || !player || replying || llmReplying || !line.trim()}>
            {llmReplying ? 'LLM Thinking…' : 'Generate LLM Reply'}
          </button>

          <button onClick={exportAll}>Export JSON</button>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ border: '1px solid #ccc', padding: '6px 10px', borderRadius: 6, cursor: 'pointer' }}>
              Import JSON
            </span>
            <input type="file" accept="application/json" style={{ display: 'none' }}
              onChange={(e) => importAll(e.target.files?.[0])} />
          </label>
        </div>

        {reply && (
          <div style={{ marginTop: 10, padding: 10, border: '1px solid #ddd', borderRadius: 8 }}>
            <strong>Reply</strong>
            <div>{reply}</div>
          </div>
        )}

        <p style={{ opacity: 0.7, marginTop: 8 }}>
          Tip: start a conversation, add a confess line like “i still owe you 10 gold”, then Retrieve or Generate Fake Reply.
        </p>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <strong>{f.text}</strong>
              <span>score: {f.score}</span>
            </div>
            <div style={{ fontSize: 12, opacity: 0.8 }}>
              scene: {f.scene || '—'} | weight: {Number(f.weight).toFixed(2)} | pinned: {String(f.pinned)} | intent: {f.intent || '—'}
            </div>
            <div style={{ fontSize: 12, opacity: 0.8, marginTop: 4 }}>
              tags: {(f.tags || []).join(', ') || '—'}
            </div>
            {showDebug && f.debug && (
              <div style={{ fontSize: 11, opacity: 0.7, marginTop: 4 }}>
                base {f.debug.base} · intent {f.debug.intent_bonus} · assoc {f.debug.assoc_bonus}
              </div>
            )}
            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!f.pinned ? (
                <button onClick={() => togglePin(f.fact_id, true)}>Pin</button>
              ) : (
                <button onClick={() => togglePin(f.fact_id, false)}>Unpin</button>
              )}
              <button onClick={() => sendFeedback(f.fact_id, +1, f.weight)}>👍</button>
              <button onClick={() => sendFeedback(f.fact_id, -1, f.weight)}>👎</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}