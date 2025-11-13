insert into entities (id,kind) values
  ('npc:bartender','npc'),
  ('player:demo','player')
on conflict do nothing;
