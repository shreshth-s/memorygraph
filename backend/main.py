from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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

@app.get("/v0/retrieve")
def retrieve(
    npc_id: str = Query(...),
    player_id: str = Query(...),
    scene: Optional[str] = None,
    intent: Optional[str] = None,
    k: int = 6,
):
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
        base = 0.9*float(r["weight"]) + 0.1*scene_match
        intent_bonus = 0.0
        if intent:
            t = r["tags"] or []
            if intent == r.get("intent") or intent in t:
                intent_bonus = 0.2
        score = base + intent_bonus
        out.append({
            "fact_id": str(r["id"]),
            "text": r["text"],
            "tags": r["tags"],
            "weight": float(r["weight"]),
            "pinned": bool(r["pinned"]),
            "scene": r["scene"],
            "intent": r["intent"],
            "score": round(score, 4),
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
