
begin;
create function vocab_teacher.research(teacher_issuer text, teacher_subject text, filters jsonb)
returns jsonb language plpgsql stable security definer set search_path = '' as $body$
declare
  date_from date := (filters->>'from')::date;
  date_to date := (filters->>'to')::date;
begin
  if not exists (select from vocab_teacher.identities i
    where i.issuer=teacher_issuer and i.subject=teacher_subject and i.active) then
    raise exception 'teacher_denied';
  end if;
  if date_from is null or date_to is null or date_to-date_from not between 0 and 365 then
    raise exception 'invalid_date_range';
  end if;

  return (with owned_daily as materialized (
    select d.* from vocab_private.daily d
    join vocab_teacher.resources c on (c.kind,c.name,c.issuer,c.subject)=('course',d.course_id,teacher_issuer,teacher_subject)
    join vocab_teacher.resources s on (s.kind,s.name,s.issuer,s.subject)=('student',d.student_code,teacher_issuer,teacher_subject)
    where d.practice_date between date_from and date_to
      and (nullif(filters->>'student','') is null or d.student_code=filters->>'student')
      and (nullif(filters->>'course','') is null or d.course_id=filters->>'course')
    order by d.practice_date,d.session_id limit 5001
  ), owned_events as (
    select d.student_code,d.course_id,d.course_version,d.practice_date,d.session_id,
      e.event_id,e.received_at,e.correct_server,e.payload->>'stage' as stage,
      e.payload->>'action' as action,e.payload->>'mode' as mode,
      e.payload->>'clientTime' as client_time,e.payload->>'selected' as selected,
      e.payload->>'attempt' as attempt,e.payload->>'wordAttempt' as word_attempt,
      e.payload->>'firstAttempt' as first_attempt,e.payload->>'sequence' as sequence,
      e.payload->>'wordErrorCount' as word_error_count,
      e.payload->>'submissionId' as submission_id,e.payload->>'questionType' as question_type,
      e.payload->>'elapsedSessionMs' as elapsed_session_ms,
      e.payload->>'elapsedMatchMs' as elapsed_match_ms,
      e.payload->>'elapsedClozeRoundMs' as elapsed_cloze_round_ms,
      e.payload->>'selectionLatencyMs' as selection_latency_ms,
      e.payload->>'inputMethod' as input_method,e.payload->>'wordId' as word_id,
      w.item->>'word' as target_word,w.item->'accepted' as accepted,
      coalesce(w.item->>'category','unknown') as category,
      case when e.payload->>'questionType'='context_cloze' and w.item is not null
           then vocab_private.norm(e.payload->>'selected')=vocab_private.norm(w.item->>'word') end as target_hit
    from owned_daily d
    join vocab_private.events e using(session_id)
    join vocab_private.courses v on (v.id,v.version)=(d.course_id,d.course_version)
    left join lateral (select item from jsonb_array_elements(v.document->'words') item
      where item->>'id'=e.payload->>'wordId') w on true
    where (nullif(filters->>'word','') is null or filters->>'word' in (w.item->>'word',e.payload->>'wordId'))
      and (nullif(filters->>'category','') is null or (w.item is not null and coalesce(w.item->>'category','unknown')=filters->>'category'))
    order by d.practice_date,e.received_at,e.event_id limit 5001
  ), scoped_words as (
    select distinct v.id as course_id,v.version as course_version,item->>'id' as word_id,
      item->>'word' as target_word,item->'accepted' as accepted,coalesce(item->>'category','unknown') as category
    from vocab_private.courses v
    join vocab_teacher.resources c on (c.kind,c.name,c.issuer,c.subject)=('course',v.id,teacher_issuer,teacher_subject)
    cross join lateral jsonb_array_elements(v.document->'words') item
    where (nullif(filters->>'course','') is null or v.id=filters->>'course')
      and (nullif(filters->>'student','') is null or exists (
        select from owned_daily d where (d.course_id,d.course_version)=(v.id,v.version)
      ))
      and (nullif(filters->>'word','') is null or filters->>'word' in (item->>'word',item->>'id'))
      and (nullif(filters->>'category','') is null or coalesce(item->>'category','unknown')=filters->>'category')
    order by 1,2,3 limit 5001
  )
  select case when (select count(*) from owned_daily)>5000 or (select count(*) from owned_events)>5000
      or (select count(*) from scoped_words)>5000 then '{"overflow":true}'::jsonb
    else jsonb_build_object(
    'sessions',coalesce((select jsonb_agg(to_jsonb(d) order by practice_date,session_id) from owned_daily d),'[]'),
    'events',coalesce((select jsonb_agg(to_jsonb(e) order by practice_date,received_at,event_id) from owned_events e),'[]'),
    'words',coalesce((select jsonb_agg(to_jsonb(w) order by course_id,course_version,word_id) from scoped_words w),'[]')
  ) end);
end
$body$;
revoke all on function vocab_teacher.research(text,text,jsonb) from public, anon, authenticated;
grant execute on function vocab_teacher.research(text,text,jsonb) to vocab_teacher_runtime;
commit;
