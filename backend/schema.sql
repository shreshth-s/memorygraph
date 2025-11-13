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
