import random
import os
import json
import requests
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional
from db import conn

# --- NEW: Import SentenceTransformer ---
from sentence_transformers import SentenceTransformer

# 1. Load environment variables (e.g., OPENROUTER_API_KEY)
load_dotenv()

app = FastAPI(title="MemoryGraph API", version="0.2.0")

# --- NEW: Load Model (Global) ---
# This downloads ~80MB on first run. It is free and local.
print("Loading embedding model (all-MiniLM-L6-v2)...")
encoder = SentenceTransformer('all-MiniLM-L6-v2')
print("Model loaded.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def cosine_similarity(a, b):
    if not a or not b: return 0.0
    a = np.array(a)
    b = np.array(b)
    if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

@app.get("/v0/health")
def health():
    return {"ok": True}

@app.get("/v0/entities")
def entities(kind: Optional[str] = None):
    with conn() as c, c.cursor() as cur:
        if kind:
            cur.execute("select id, kind from entities where kind=%s order by id", (kind,))
        else:
            cur.execute("select id, kind from entities order by kind, id")
        return cur.fetchall()

@app.post("/v0/facts.add")
def facts_add(payload: dict):
    for k in ["who","about","text"]:
        if k not in payload: raise HTTPException(400, f"missing {k}")
    who    = payload["who"]
    about  = payload["about"]
    text   = payload["text"]
    scene  = payload.get("scene")
    ftype  = payload.get("type")
    intent = payload.get("intent")
    tags   = payload.get("tags", [])
    weight = float(payload.get("weight", 0.5))
    pinned = bool(payload.get("pinned", False))

    # --- NEW: Compute Embedding (Free & Local) ---
    embedding = encoder.encode(text).tolist()

    with conn() as c, c.cursor() as cur:
        cur.execute("""
          insert into facts (who,about,scene,type,intent,text,tags,weight,pinned,embedding)
          values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
          returning id
        """,(who,about,scene,ftype,intent,text,tags,weight,pinned,embedding))
        row = cur.fetchone(); c.commit()
        return {"fact_id": str(row["id"])}

def jaccard(a, b):
    sa, sb = set(a or []), set(b or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

@app.get("/v0/retrieve")
def retrieve(
    npc_id: str = Query(...),
    player_id: str = Query(...),
    scene: str | None = None,
    intent: str | None = None,
    k: int = 6,
    conversation_id: str | None = None,
    query: str | None = None, # --- NEW: Query param
):
    conv_tags = []
    if conversation_id:
        with conn() as c, c.cursor() as cur:
            cur.execute("select tags from conversations where id=%s", (conversation_id,))
            r = cur.fetchone()
            if r:
                conv_tags = r["tags"] or []

    # --- NEW: Compute Query Embedding if query exists ---
    query_emb = None
    if query and query.strip():
        query_emb = encoder.encode(query.strip()).tolist()

    with conn() as c, c.cursor() as cur:
        # Fetch embedding column too
        cur.execute("""
          select id, text, tags, weight, pinned, scene, intent, embedding
          from facts
          where who=%s and about=%s
          order by created_at desc
          limit 100
        """, (npc_id, player_id))
        rows = cur.fetchall()

    out = []
    for r in rows:
        # 1. Heuristic Score (Old Way)
        scene_match = 1.0 if (scene and r["scene"] == scene) else 0.0
        base = 0.9 * float(r["weight"]) + 0.1 * scene_match
        intent_bonus = 0.2 if intent and (intent == r["intent"] or intent in (r["tags"] or [])) else 0.0
        assoc_bonus = 0.15 * jaccard(r["tags"] or [], conv_tags)
        
        heuristic_score = base + intent_bonus + assoc_bonus

        # 2. Semantic Score (New Way)
        vector_score = 0.0
        if query_emb and r["embedding"]:
            vector_score = cosine_similarity(query_emb, r["embedding"])
        
        # 3. Blend Scores
        # If query exists: 70% Semantic + 30% Heuristic
        # If no query: 100% Heuristic
        if query_emb:
            final_score = (0.7 * vector_score) + (0.3 * heuristic_score)
        else:
            final_score = heuristic_score

        out.append({
            "fact_id": str(r["id"]),
            "text": r["text"],
            "tags": r["tags"],
            "weight": float(r["weight"]),
            "pinned": bool(r["pinned"]),
            "scene": r["scene"],
            "intent": r["intent"],
            "score": round(final_score, 4),
            "debug": {
                "heuristic": round(heuristic_score, 4),
                "vector": round(vector_score, 4),
                "blended": True if query_emb else False
            }
        })

    out = sorted(out, key=lambda x: (not x["pinned"], -x["score"]))[:k]
    return out

@app.post("/v0/pin")
def pin(payload: dict):
    if "fact_id" not in payload or "pinned" not in payload:
        raise HTTPException(400, "fact_id and pinned required")
    with conn() as c, c.cursor() as cur:
        cur.execute("update facts set pinned=%s where id=%s returning id",
                    (bool(payload["pinned"]), payload["fact_id"]))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "fact not found")
        c.commit(); return {"ok": True, "fact_id": str(row["id"])}

@app.post("/v0/feedback")
def feedback(payload: dict):
    fid = payload.get("fact_id"); reward = float(payload.get("reward", 0))
    if not fid: raise HTTPException(400, "fact_id required")
    alpha = 0.1
    with conn() as c, c.cursor() as cur:
        cur.execute("select weight, reward_sum, reward_count from facts where id=%s",(fid,))
        row = cur.fetchone()
        if not row: raise HTTPException(404, "fact not found")
        old = float(row["weight"])
        rsum = float(row["reward_sum"] or 0) + reward
        rcnt = int(row["reward_count"] or 0) + 1
        neww = max(0.0, min(1.0, old + alpha*reward))
        cur.execute("""
          update facts set weight=%s, reward_sum=%s, reward_count=%s where id=%s
        """, (neww, rsum, rcnt, fid))
        c.commit()
        return {"ok": True, "fact_id": fid, "old_weight": old, "new_weight": neww}

@app.post("/v0/conversations.start")
def conv_start(payload: dict):
    npc = payload.get("npc_id"); player = payload.get("player_id"); scene = payload.get("scene")
    if not npc or not player: raise HTTPException(400, "npc_id and player_id required")
    with conn() as c, c.cursor() as cur:
        cur.execute("insert into conversations (npc,player,scene) values (%s,%s,%s) returning id",
                    (npc,player,scene))
        row = cur.fetchone(); c.commit()
        return {"conversation_id": str(row["id"])}

@app.post("/v0/conversations.attach")
def conv_attach(payload: dict):
    from fastapi import HTTPException
    cid = payload.get("conversation_id")
    fact_ids = [fid for fid in payload.get("fact_ids", []) if fid]

    if not cid or not fact_ids:
        raise HTTPException(400, "conversation_id and fact_ids required")

    try:
        with conn() as c, c.cursor() as cur:
            cur.execute("select 1 from conversations where id=%s", (cid,))
            if not cur.fetchone():
                raise HTTPException(400, f"conversation_id not found: {cid}")

            cur.execute("select count(*) as n from facts where id = any(%s)", (fact_ids,))
            n = cur.fetchone()["n"]
            if n != len(fact_ids):
                raise HTTPException(400, f"one or more fact_ids not found ({n}/{len(fact_ids)} exist)")

            for fid in fact_ids:
                cur.execute("""
                    insert into conversation_facts (conversation_id, fact_id)
                    values (%s, %s)
                    on conflict do nothing
                """, (cid, fid))

            cur.execute("""
            update conversations
                set tags = coalesce((
                select array_agg(distinct t.tag)
                    from (
                    select unnest(coalesce(f.tags, '{}'::text[])) as tag
                        from facts f
                        join conversation_facts cf on cf.fact_id = f.id
                        where cf.conversation_id = %s
                    ) t
                ), '{}'::text[])
            where id = %s
            """, (cid, cid))
            c.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"attach_failed: {e}")

@app.get("/v0/export")
def export_all():
    with conn() as c, c.cursor() as cur:
        cur.execute("select id, kind from entities order by id")
        entities = cur.fetchall()
        cur.execute("""
          select id, who, about, scene, type, intent, text, tags, weight, pinned, created_at, embedding
            from facts
           order by created_at asc
        """)
        facts = cur.fetchall()
        # Convert numpy arrays to lists for JSON serialization
        for f in facts:
            if f.get("embedding"):
                f["embedding"] = list(f["embedding"])
        return {"entities": entities, "facts": facts}

@app.post("/v0/import")
def import_all(payload: dict):
    ents = payload.get("entities", [])
    facts = payload.get("facts", [])
    with conn() as c, c.cursor() as cur:
        for e in ents:
            cur.execute("""
              insert into entities (id, kind) values (%s, %s)
              on conflict (id) do nothing
            """, (e["id"], e["kind"]))
        for f in facts:
            cur.execute("""
              insert into facts (id, who, about, scene, type, intent, text, tags, weight, pinned, created_at, embedding)
              values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              on conflict (id) do nothing
            """, (
                f["id"], f["who"], f["about"], f["scene"], f["type"], f.get("intent"),
                f["text"], f.get("tags") or [], f.get("weight", 0.5), f.get("pinned", False),
                f.get("created_at"),
                f.get("embedding") # Import embedding if present
            ))
        c.commit()
    return {"ok": True}

def _npc_name(npc_id: str) -> str:
    return npc_id.split(":")[-1] if ":" in npc_id else npc_id

def _fake_reply_line(npc_name: str, scene: str, intent: str | None, user_text: str, facts: list[dict]) -> str:
    top = facts[0] if facts else None
    mem = (top or {}).get("text", "")
    intent = (intent or "").strip().lower()
    rng = random.Random((npc_name + scene + (mem or "") + (intent or "")).encode("utf-8"))
    pick = lambda xs: xs[rng.randrange(len(xs))]

    def hint_from_mem(m: str) -> str:
        if not m: return ""
        s = m.strip().rstrip(".!?")
        if len(s) > 80: s = s[:80].rsplit(" ", 1)[0]
        return s

    h = hint_from_mem(mem)
    templates = {
        "confess": [
            f"look… about earlier — {h}… i owe you for that.",
            f"alright, i’ll come clean: {h.lower()} — that’s on me.",
            f"you’re right. i haven’t forgotten — {h.lower()}."
        ],
        "deny": [
            f"nah, that’s not how it happened. you’ve got it twisted.",
            f"who told you that? {h.lower()}? no chance.",
            f"i don’t buy it. rumors don’t make it true."
        ],
        "ask_favor": [
            f"listen, can you help me with {h.lower() or 'something in the back'}?",
            f"could use a hand — small favor, won’t take long.",
            f"mind doing me a solid? i’ll make it worth your while."
        ],
        "gift_help": [
            f"here — take this. call it thanks for {h.lower() or 'stopping by'}.",
            f"i set something aside for you; you’ve earned it.",
            f"i can help — say the word and it’s yours."
        ],
        "threaten": [
            f"careful. keep pushing and you won’t like what follows.",
            f"watch it. i’ve got eyes in this {scene}.",
            f"back off. last warning."
        ],
        "default": [
            f"yeah? i hear you. about {h.lower() or 'that'}, what do you want from me?",
            f"alright — let’s talk. where do you want to take this?",
            f"fine. say your piece and i’ll say mine."
        ]
    }
    bank = templates.get(intent, templates["default"])
    line = pick(bank)
    return f"{npc_name}: {line}"

def _call_openrouter(system_prompt: str, user_prompt: str, model: str) -> str:
    """Helper to call OpenRouter API."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(500, "OPENROUTER_API_KEY not set in environment")

    try:
        res = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model, 
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            },
            timeout=25
        )
        res.raise_for_status()
        data = res.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(502, f"OpenRouter HTTP error: {e}")
    except Exception as e:
        raise HTTPException(500, f"OpenRouter call failed: {e.__class__.__name__}: {e}")

@app.post("/v0/reply")
def v0_reply_llm(payload: dict):
    try:
        npc_id = payload["npc_id"]
        player_id = payload["player_id"]
        scene = payload.get("scene", "tavern")
        user_text = payload.get("user_text", "")
        if not user_text: raise HTTPException(400, "user_text required for LLM reply")
        intent = payload.get("intent")
        conv_id = payload.get("conversation_id")
        
        npc_name = _npc_name(npc_id)
        model = payload.get("model", "mistralai/mistral-7b-instruct:free") 

        # 1) Reuse retrieve (k=4) + Semantic Query
        params = {"npc_id": npc_id, "player_id": player_id, "scene": scene, "k": 4, "query": user_text} 
        if intent: params["intent"] = intent
        if conv_id: params["conversation_id"] = conv_id

        r = requests.get("http://127.0.0.1:8000/v0/retrieve", params=params, timeout=15)
        r.raise_for_status()
        facts = r.json() or []
        used_ids = [f["fact_id"] for f in facts]

        # 2) Best-effort attach
        if conv_id and used_ids:
            try:
                requests.post(
                    "http://127.0.0.1:8000/v0/conversations.attach",
                    json={"conversation_id": conv_id, "fact_ids": used_ids},
                    timeout=10
                )
            except Exception: pass 

        # 3) Format prompt and call LLM
        memory_str = "\n".join(f"- {f['text']}" for f in facts) or "None."

        system_prompt = f"""
You are {npc_name}, an NPC in a game.
Your current location is: {scene}.
You are speaking to {player_id}.

Rules:
1. Be concise and natural.
2. Use these relevant memories:
{memory_str}
3. Do NOT break character.
"""
        
        line = _call_openrouter(system_prompt.strip(), user_text, model)
        if line.lower().startswith(f"{npc_name.lower()}:"):
            line = line[len(npc_name)+1:].strip()

        return {"reply": line, "used_fact_ids": used_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"llm_reply_failed: {e}")


@app.post("/v0/reply.fake")
def v0_reply_fake(payload: dict):
    try:
        npc_id = payload["npc_id"]
        player_id = payload["player_id"]
        scene = payload.get("scene", "tavern")
        user_text = payload.get("user_text", "")
        intent = payload.get("intent")
        conv_id = payload.get("conversation_id")

        # Reuse retrieve (with optional semantic query if text exists)
        params = {"npc_id": npc_id, "player_id": player_id, "scene": scene}
        if user_text: params["query"] = user_text
        if intent: params["intent"] = intent
        if conv_id: params["conversation_id"] = conv_id

        r = requests.get("http://127.0.0.1:8000/v0/retrieve", params=params, timeout=15)
        r.raise_for_status()
        facts = r.json() or []
        used_ids = [f["fact_id"] for f in facts]

        if conv_id and used_ids:
            try:
                requests.post(
                    "http://127.0.0.1:8000/v0/conversations.attach",
                    json={"conversation_id": conv_id, "fact_ids": used_ids},
                    timeout=10
                )
            except Exception: pass

        npc_name = _npc_name(npc_id)
        line = _fake_reply_line(npc_name, scene, intent, user_text, facts)

        return {"reply": line, "used_fact_ids": used_ids}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fake_reply_failed: {e}" )