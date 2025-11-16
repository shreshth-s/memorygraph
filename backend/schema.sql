create extension if not exists pgcrypto;

create table if not exists entities (
  id   text primary key,
  kind text not null check (kind in ('npc','player'))
);

create table if not exists facts (
  id uuid primary key default gen_random_uuid(),
  who   text not null references entities(id),
  about text not null references entities(id),
  scene text,
  type  text,
  intent text,
  text  text not null,
  tags  text[] default '{}',
  weight real default 0.5,
  pinned boolean default false,
  reward_sum real default 0,
  reward_count int default 0,
  created_at timestamptz default now()
);

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  npc text not null references entities(id),
  player text not null references entities(id),
  scene text,
  tags text[] default '{}',
  created_at timestamptz default now()
);

create table if not exists conversation_facts (
  conversation_id uuid references conversations(id) on delete cascade,
  fact_id uuid references facts(id) on delete cascade,
  primary key (conversation_id, fact_id)
);
