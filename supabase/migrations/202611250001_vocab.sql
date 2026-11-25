begin;
create schema if not exists extensions;
create extension if not exists pgcrypto with schema extensions;
create schema if not exists vocab_private;
revoke all on schema vocab_private from public, anon, authenticated;

create table vocab_private.students (
  code text primary key check (code ~ '^[A-Za-z0-9_-]{3,32}$'),
  pin_hash text not null,
  active boolean not null default true
);
create table vocab_private.attempt_limits (
  code text primary key references vocab_private.students(code),
  failures integer not null default 0,
  since timestamptz not null default now()
);
create table vocab_private.courses (
  id text not null, version text not null, document jsonb not null,
  active boolean not null default true,
  primary key (id, version)
);
create table vocab_private.daily (
  student_code text not null references vocab_private.students(code),
  course_id text not null, practice_date date not null, course_version text not null,
  session_id text not null unique, completed_at timestamptz,
  started_at timestamptz not null default now(),
  primary key (student_code, course_id, practice_date),
  foreign key (course_id, course_version) references vocab_private.courses(id, version)
);
create table vocab_private.events (
  event_id text primary key, session_id text not null references vocab_private.daily(session_id),
  received_at timestamptz not null default now(), correct_server boolean, payload jsonb not null
);
create index vocab_events_session on vocab_private.events(session_id);

create view vocab_private.research_events as
select e.received_at as server_time, e.event_id, d.student_code, d.course_id,
       d.course_version as version, e.payload->>'mode' as mode,
       e.payload->>'stage' as stage, e.payload->>'action' as action,
       e.payload->>'wordId' as word_id, e.payload->>'word' as word,
       e.payload->>'questionType' as question_type, e.payload->>'selected' as selected,
       e.correct_server, e.payload->'correct' as correct_client,
       e.payload->>'inputMethod' as input_method, e.payload->'round' as round,
       e.payload->'attempt' as attempt, e.payload->>'clientTime' as client_time,
       e.payload - array['eventId','clientTime','study','studentCode','courseId','courseVersion',
         'mode','stage','action','wordId','word','questionType','selected','correct','inputMethod','round','attempt'] as extra_json,
       e.session_id, d.practice_date
from vocab_private.events e join vocab_private.daily d using (session_id);

create view vocab_private.research_sessions as
select server_time, student_code, course_id, version, mode, action, event_id, session_id, practice_date
from vocab_private.research_events where action in ('session_start','session_complete');

alter table vocab_private.students enable row level security;
alter table vocab_private.attempt_limits enable row level security;
alter table vocab_private.courses enable row level security;
alter table vocab_private.daily enable row level security;
alter table vocab_private.events enable row level security;
revoke all on all tables in schema vocab_private from public, anon, authenticated;

create function vocab_private.norm(value text) returns text
language sql immutable set search_path = '' as $$
  select regexp_replace(normalize(coalesce(value, ''), NFKC), '[[:space:]　，。！？,.!?]', '', 'g')
$$;

create function vocab_private.register_student(code text, pin text) returns void
language plpgsql set search_path = '' as $$
begin
  if pin is null or char_length(pin) < 8 or octet_length(pin) > 72 then
    raise exception 'PIN must contain at least 8 characters and at most 72 UTF-8 bytes';
  end if;
  insert into vocab_private.students values (code, extensions.crypt(pin, extensions.gen_salt('bf', 10)), true);
end
$$;

create function vocab_private.register_course(document jsonb) returns void
language plpgsql set search_path = '' as $$
begin
  if coalesce(document->>'id','') !~ '^[A-Za-z0-9_.-]{1,90}$'
    or coalesce(document->>'version','') !~ '^[A-Za-z0-9_.-]{1,90}$'
    or jsonb_typeof(document->'words') is distinct from 'array' then
    raise exception 'invalid_course';
  end if;
  if jsonb_array_length(document->'words') = 0 or exists (
    select 1 from jsonb_array_elements(document->'words') w
    where coalesce(w->>'id','') !~ '^[A-Za-z0-9_.-]{1,90}$'
      or vocab_private.norm(w->>'word') = ''
      or jsonb_typeof(w->'meanings') is distinct from 'object'
      or (w ? 'accepted' and jsonb_typeof(w->'accepted') is distinct from 'array')
  ) or (select count(distinct w->>'id') from jsonb_array_elements(document->'words') w) <> jsonb_array_length(document->'words') then
    raise exception 'invalid_words';
  end if;
  perform nullif(document->>'practiceOpenAt','')::timestamptz;
  insert into vocab_private.courses values (document->>'id', document->>'version', document, true);
end
$$;

create function public.vocab_request(packet jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  op text := packet->>'operation';
  requested_code text := packet->>'studentCode';
  course text := packet->>'courseId';
  ver text := packet->>'courseVersion';
  pin text := packet->>'pin';
  sid text := packet->>'sessionId';
  today date := (statement_timestamp() at time zone 'Asia/Taipei')::date;
  ack jsonb := jsonb_build_object('appVersion','0.3.11','protocol','supabase-v1','requestId',packet->>'requestId');
  account vocab_private.students%rowtype;
  limit_record vocab_private.attempt_limits%rowtype;
  daily_record vocab_private.daily%rowtype;
  course_record vocab_private.courses%rowtype;
  previous vocab_private.events%rowtype;
  batch jsonb := packet->'events';
  item jsonb;
  word jsonb;
  submission text;
  correct boolean;
  ids jsonb := '[]'::jsonb;
  duplicate boolean;
  created boolean := false;
  finished boolean := false;
  submitted_count integer;
begin
  if op = 'version' then return ack || '{"ok":true}'::jsonb; end if;
  if packet->>'protocol' is distinct from 'supabase-v1' then
    return ack || '{"ok":false,"error":"protocol_update_required"}'::jsonb;
  end if;
  if octet_length(packet::text) > 240000 then
    return ack || '{"ok":false,"error":"payload_invalid","permanent":true}'::jsonb;
  end if;
  if coalesce(requested_code,'') !~ '^[A-Za-z0-9_-]{3,32}$' or pin is null or octet_length(pin) not between 8 and 72 then
    return ack || '{"ok":false,"error":"auth_failed"}'::jsonb;
  end if;

  select s.* into account from vocab_private.students s where s.code = requested_code and s.active;
  if not found then return ack || '{"ok":false,"error":"auth_failed"}'::jsonb; end if;
  insert into vocab_private.attempt_limits values (requested_code) on conflict do nothing;
  select a.* into limit_record from vocab_private.attempt_limits a where a.code = account.code for update;
  if limit_record.since <= now() - interval '15 minutes' and limit_record.failures > 0 then
    update vocab_private.attempt_limits a set failures = 0, since = now() where a.code = account.code;
    limit_record.failures := 0;
  end if;
  if limit_record.failures >= 12 then return ack || '{"ok":false,"error":"temporary_auth_lock"}'::jsonb; end if;
  if extensions.crypt(pin, account.pin_hash) <> account.pin_hash then
    update vocab_private.attempt_limits a set failures = failures + 1,
      since = case when failures = 0 then now() else since end where a.code = account.code;
    return ack || '{"ok":false,"error":"auth_failed"}'::jsonb;
  end if;
  if limit_record.failures > 0 then
    update vocab_private.attempt_limits a set failures = 0 where a.code = account.code;
  end if;

  begin
    if op in ('daily_status','daily_start') then
      if coalesce(course,'') !~ '^[A-Za-z0-9_.-]{1,90}$' then raise exception 'invalid_course'; end if;
      select d.* into daily_record from vocab_private.daily d
      where d.student_code = account.code and d.course_id = course and d.practice_date = today;
      if not found and op = 'daily_start' then
        if packet->>'practiceDate' is distinct from today::text then raise exception 'daily_date_changed'; end if;
        if coalesce(sid,'') !~ '^[A-Za-z0-9_-]{20,90}$' then raise exception 'invalid_session'; end if;
        if not exists (select 1 from vocab_private.courses c where c.id = course and c.version = ver and c.active) then
          raise exception 'course_not_registered';
        end if;
        if exists (select 1 from vocab_private.courses c where c.id = course and c.version = ver
                   and nullif(c.document->>'practiceOpenAt','')::timestamptz > now()) then
          raise exception 'practice_not_open';
        end if;
        insert into vocab_private.daily(student_code,course_id,practice_date,course_version,session_id)
          values (account.code,course,today,ver,sid) returning * into daily_record;
        created := true;
      end if;
      return ack || jsonb_build_object('ok',true,'created',created,'practiceDate',today,'courseId',course,
        'status',case when daily_record.session_id is null then 'not_started'
                      when daily_record.completed_at is null then 'in_progress' else 'completed' end,
        'courseVersion',coalesce(daily_record.course_version,''),
        'sessionId',case when daily_record.session_id = sid then sid else '' end);
    end if;

    if op is distinct from 'events' or jsonb_typeof(batch) is distinct from 'array' then raise exception 'invalid_batch'; end if;
    if jsonb_array_length(batch) not between 1 and 20 then raise exception 'invalid_batch'; end if;
    item := batch->0;
    course := item->>'courseId'; ver := item->>'courseVersion'; sid := item->>'sessionId';
    select d.* into daily_record from vocab_private.daily d where d.session_id = sid and d.student_code = account.code;
    if not found or daily_record.course_id is distinct from course or daily_record.course_version is distinct from ver then
      raise exception 'daily_session_mismatch';
    end if;
    select c.* into course_record from vocab_private.courses c where c.id = course and c.version = ver;
    for item in select value from jsonb_array_elements(batch) loop
      if jsonb_typeof(item) is distinct from 'object' then raise exception 'invalid_event'; end if;
      item := item - array['pin','password','token','apikey','serviceRoleKey'];
      if item->>'studentCode' is distinct from account.code or item->>'courseId' is distinct from course
        or item->>'courseVersion' is distinct from ver or item->>'sessionId' is distinct from sid
        or item->>'practiceDate' is distinct from daily_record.practice_date::text then raise exception 'mixed_batch_scope'; end if;
      if coalesce(item->>'eventId','') !~ '^[A-Za-z0-9_.-]{1,90}$' or ids ? (item->>'eventId')
        or item->>'study' is distinct from 'vocab' or item->>'mode' is distinct from 'practice'
        or coalesce(item->>'stage','') not in ('card','match','cloze','system')
        or coalesce(item->>'action','') not in ('session_start','stage_start','stage_pass','card_flip','card_audio','card_next',
            'answer','round_end','speech_transcript','speech_error','session_complete') then raise exception 'invalid_event'; end if;
      ids := ids || jsonb_build_array(item->>'eventId');
      select e.* into previous from vocab_private.events e where e.event_id = item->>'eventId';
      duplicate := found;
      if duplicate and previous.payload is distinct from item then raise exception 'event_id_conflict'; end if;
      if duplicate then
        finished := finished or (item->>'action' = 'session_complete' and daily_record.completed_at is not null);
        continue;
      end if;
      if daily_record.completed_at is not null then raise exception 'daily_already_completed'; end if;
      if not course_record.active then raise exception 'course_not_active'; end if;
      correct := null;
      if item->>'action' = 'answer' then
        select w into word from jsonb_array_elements(course_record.document->'words') w where w->>'id' = item->>'wordId';
        if not found then raise exception 'word_not_registered'; end if;
        if item->>'stage' = 'match' and item->>'questionType' = 'meaning_match' then
          if coalesce(word->'meanings'->>(item->>'meaningLanguage'),'') = '' then raise exception 'language_not_available'; end if;
          correct := item->>'selectedWordId' is not distinct from item->>'wordId'
            and vocab_private.norm(item->>'selected') = vocab_private.norm(word->'meanings'->>(item->>'meaningLanguage'));
        elsif item->>'stage' = 'cloze' and item->>'questionType' = 'context_cloze' then
          if coalesce(item->>'submissionId','') !~ '^[A-Za-z0-9_-]{20,90}$' then raise exception 'invalid_submission'; end if;
          correct := vocab_private.norm(item->>'selected') <> '' and (
            vocab_private.norm(item->>'selected') = vocab_private.norm(word->>'word')
            or exists(select 1 from jsonb_array_elements_text(coalesce(word->'accepted','[]'::jsonb)) a
                      where vocab_private.norm(a) = vocab_private.norm(item->>'selected')));
        else raise exception 'invalid_question'; end if;
      end if;
      begin
        insert into vocab_private.events(event_id,session_id,correct_server,payload) values(item->>'eventId',sid,correct,item);
      exception when unique_violation then raise exception 'event_id_conflict';
      end;
      if item->>'action' = 'session_complete' then
        submission := item->>'submissionId';
        if item->>'stage' is distinct from 'cloze' or coalesce(submission,'') !~ '^[A-Za-z0-9_-]{20,90}$' then
          raise exception 'invalid_submission';
        end if;
        select count(*) into submitted_count from vocab_private.events e where e.session_id = sid
          and e.payload->>'questionType' = 'context_cloze' and e.payload->>'action' = 'answer' and e.payload->>'submissionId' = submission;
        if submitted_count <> jsonb_array_length(course_record.document->'words') or exists (
          select 1 from jsonb_array_elements(course_record.document->'words') w
          where not exists(select 1 from vocab_private.events e where e.session_id = sid and e.correct_server
            and e.payload->>'questionType' = 'meaning_match' and e.payload->>'wordId' = w->>'id')
          or not exists(select 1 from vocab_private.events e where e.session_id = sid and e.correct_server
            and e.payload->>'questionType' = 'context_cloze' and e.payload->>'wordId' = w->>'id'
            and e.payload->>'submissionId' = submission and e.payload->>'round' = item->>'round')
        ) or not exists(select 1 from vocab_private.events e where e.session_id = sid and e.payload->>'action' = 'stage_pass'
                       and e.payload->>'stage' = 'match')
          or not exists(select 1 from vocab_private.events e where e.session_id = sid and e.payload->>'action' = 'stage_pass'
                       and e.payload->>'stage' = 'cloze' and e.payload->>'submissionId' = submission) then
          raise exception 'daily_completion_not_verified';
        end if;
        update vocab_private.daily d set completed_at = now() where d.session_id = sid returning * into daily_record;
        finished := true;
      end if;
    end loop;
    return ack || jsonb_build_object('ok',true,'eventIds',ids,
      'completedSessions',case when finished then jsonb_build_array(sid) else '[]'::jsonb end);
  exception when raise_exception then
    return ack || jsonb_build_object('ok',false,'error',sqlerrm,'permanent',op = 'events');
  end;
end
$$;

revoke execute on all functions in schema vocab_private from public, anon, authenticated;
revoke execute on function public.vocab_request(jsonb) from public, anon, authenticated;
grant execute on function public.vocab_request(jsonb) to anon;
commit;
