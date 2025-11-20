import random
import os,json
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from dotenv import load_dotenv
from typing import Optional
from db import conn

app = FastAPI(title="MemoryGraph API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    with conn() as c, c.cursor() as cur:
        cur.execute("""
          insert into facts (who,about,scene,type,intent,text,tags,weight,pinned)
          values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
          returning id
        """,(who,about,scene,ftype,intent,text,tags,weight,pinned))
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
):
    conv_tags = []
    if conversation_id:
        with conn() as c, c.cursor() as cur:
            cur.execute("select tags from conversations where id=%s", (conversation_id,))
            r = cur.fetchone()
            if r:
                conv_tags = r["tags"] or []

    with conn() as c, c.cursor() as cur:
        cur.execute("""
          select id, text, tags, weight, pinned, scene, intent
          from facts
          where who=%s and about=%s
          order by created_at desc
          limit 100
        """, (npc_id, player_id))
        rows = cur.fetchall()

    out = []
    for r in rows:
        scene_match = 1.0 if (scene and r["scene"] == scene) else 0.0
        base = 0.9 * float(r["weight"]) + 0.1 * scene_match
        intent_bonus = 0.2 if intent and (intent == r["intent"] or intent in (r["tags"] or [])) else 0.0
        assoc_bonus = 0.15 * jaccard(r["tags"] or [], conv_tags)
        score = base + intent_bonus + assoc_bonus
        out.append({
            "fact_id": str(r["id"]),
            "text": r["text"],
            "tags": r["tags"],
            "weight": float(r["weight"]),
            "pinned": bool(r["pinned"]),
            "scene": r["scene"],
            "intent": r["intent"],
            "score": round(score, 4),
              "debug": {
                "base": round(base, 4),
                "intent_bonus": round(intent_bonus, 4),
                "assoc_bonus": round(assoc_bonus, 4)
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
            # Verify conversation exists
            cur.execute("select 1 from conversations where id=%s", (cid,))
            if not cur.fetchone():
                raise HTTPException(400, f"conversation_id not found: {cid}")

            # Verify all facts exist
            cur.execute("select count(*) as n from facts where id = any(%s)", (fact_ids,))
            n = cur.fetchone()["n"]
            if n != len(fact_ids):
                raise HTTPException(400, f"one or more fact_ids not found ({n}/{len(fact_ids)} exist)")

            # Attach (idempotent)
            for fid in fact_ids:
                cur.execute("""
                    insert into conversation_facts (conversation_id, fact_id)
                    values (%s, %s)
                    on conflict do nothing
                """, (cid, fid))

            # Roll up tags
# 4) roll up tags from attached facts (distinct)
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
        # surface the DB error text for debugging instead of a 500 mystery
        raise HTTPException(400, f"attach_failed: {e}")

@app.get("/v0/export")
def export_all():
    with conn() as c, c.cursor() as cur:
        cur.execute("select id, kind from entities order by id")
        entities = cur.fetchall()
        cur.execute("""
          select id, who, about, scene, type, intent, text, tags, weight, pinned, created_at
            from facts
           order by created_at asc
        """)
        facts = cur.fetchall()
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
              insert into facts (id, who, about, scene, type, intent, text, tags, weight, pinned, created_at)
              values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
              on conflict (id) do nothing
            """, (
                f["id"], f["who"], f["about"], f["scene"], f["type"], f.get("intent"),
                f["text"], f.get("tags") or [], f.get("weight", 0.5), f.get("pinned", False),
                f.get("created_at"),
            ))
        c.commit()
    return {"ok": True}

def _npc_name(npc_id: str) -> str:
    return npc_id.split(":")[-1] if ":" in npc_id else npc_id

def _fake_reply_line(npc_name: str, scene: str, intent: str | None, user_text: str, facts: list[dict]) -> str:
    top = facts[0] if facts else None
    mem = (top or {}).get("text", "")
    intent = (intent or "").strip().lower()

    # light variation so it doesn't feel identical each time
    rng = random.Random((npc_name + scene + (mem or "") + (intent or "")).encode("utf-8"))
    pick = lambda xs: xs[rng.randrange(len(xs))]

    # small helpers to “hint” memory without copying it verbatim
    def hint_from_mem(m: str) -> str:
        if not m:
            return ""
        # grab a short clause/snippet
        s = m.strip().rstrip(".!?")
        if len(s) > 80:
            s = s[:80].rsplit(" ", 1)[0]
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

    # add speaker name
    return f"{npc_name}: {line}"
    

@app.post("/v0/reply.fake")
def v0_reply_fake(payload: dict):
    """
    Body:
    {
      "npc_id": "npc:bartender",
      "player_id": "player:demo",
      "scene": "tavern",
      "conversation_id": "uuid-optional",
      "user_text": "player message here",
      "intent": "confess"  # optional
    }
    """
    try:
        npc_id = payload["npc_id"]
        player_id = payload["player_id"]
        scene = payload.get("scene", "tavern")
        user_text = payload.get("user_text", "")
        intent = payload.get("intent")
        conv_id = payload.get("conversation_id")

        # 1) reuse retrieve
        params = {"npc_id": npc_id, "player_id": player_id, "scene": scene}
        if intent: params["intent"] = intent
        if conv_id: params["conversation_id"] = conv_id

        r = requests.get("http://127.0.0.1:8000/v0/retrieve", params=params, timeout=15)
        r.raise_for_status()
        facts = r.json() or []
        used_ids = [f["fact_id"] for f in facts]

        # 2) best-effort attach
        if conv_id and used_ids:
            try:
                requests.post(
                    "http://127.0.0.1:8000/v0/conversations.attach",
                    json={"conversation_id": conv_id, "fact_ids": used_ids},
                    timeout=10
                ).raise_for_status()
            except Exception:
                pass

        # 3) synthesize fake line
        npc_name = _npc_name(npc_id)
        line = _fake_reply_line(npc_name, scene, intent, user_text, facts)

        return {"reply": line, "used_fact_ids": used_ids}
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"missing field: {e}")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"retrieve_http_error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"fake_reply_failed: {e.__class__.__name__}: {e}" )
