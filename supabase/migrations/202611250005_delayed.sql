begin;
create table vocab_private.delayed_tests (
 student_code text not null references vocab_private.students(code),
 course_id text not null, course_version text not null,
 end_date date not null, makeup_date date check (makeup_date > end_date + 14),
 submitted_at timestamptz, test_date date,
 delay_days integer generated always as (test_date - end_date) stored,
 is_makeup boolean generated always as (test_date > end_date + 14) stored,
 primary key (student_code,course_id),
 foreign key (course_id,course_version) references vocab_private.courses(id,version)
);
create table vocab_private.delayed_answers (
 student_code text not null, course_id text not null, word_id text not null,
 actual_answer text not null, target_word text not null, category text not null,
 answer_type text not null check (answer_type in ('target','accepted_alternative','incorrect','blank')),
 target_hit boolean not null, correct_server boolean not null,
 primary key (student_code,course_id,word_id),
 foreign key (student_code,course_id) references vocab_private.delayed_tests(student_code,course_id)
);
alter table vocab_private.delayed_tests enable row level security;
alter table vocab_private.delayed_answers enable row level security;
revoke all on vocab_private.delayed_tests,vocab_private.delayed_answers from public,anon,authenticated,vocab_teacher_runtime;

create function public.vocab_delayed(packet jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 op text := packet->>'operation';
 scoped jsonb;
 assessment vocab_private.delayed_tests%rowtype;
 words jsonb;
 answers jsonb := packet->'answers';
 today date := (statement_timestamp() at time zone 'Asia/Taipei')::date;
 status text;
begin
 scoped := vocab_private.vocab_request_v1(packet || '{"operation":"daily_status"}');
 if scoped->>'ok' is distinct from 'true' then return scoped; end if;
 scoped := jsonb_build_object('ok',true,'requestId',packet->>'requestId','protocol','supabase-v1','appVersion','0.3.11');
 if op is null or op not in ('delayed_status','delayed_submit') then return scoped || '{"ok":false,"error":"invalid_operation"}'; end if;
 select * into assessment from vocab_private.delayed_tests
   where student_code=packet->>'studentCode' and course_id=packet->>'courseId' for update;
 if not found then return scoped || '{"status":"not_assigned"}'; end if;
 status := case
   when assessment.submitted_at is not null then 'submitted'
   when today between assessment.end_date+8 and assessment.end_date+14 then 'open'
   when today=assessment.makeup_date then 'open_makeup'
   when today<assessment.end_date+8 then 'not_open'
   when today<assessment.makeup_date then 'makeup_scheduled'
   else 'missing' end;
 scoped := scoped || jsonb_build_object('status',status,'courseVersion',assessment.course_version,
   'opens',assessment.end_date+8,'closes',assessment.end_date+14,'makeupDate',assessment.makeup_date);
 if op='delayed_status' or status not in ('open','open_makeup') then return scoped; end if;
 if assessment.course_version is distinct from packet->>'courseVersion' then
   return scoped || '{"ok":false,"error":"version_mismatch"}';
 end if;
 select document->'words' into words from vocab_private.courses
   where id=assessment.course_id and version=assessment.course_version;
 if jsonb_typeof(answers) is distinct from 'object' then return scoped || '{"ok":false,"error":"invalid_answers"}'; end if;
 if (select count(*) from jsonb_object_keys(answers)) <> jsonb_array_length(words)
   or exists (select from jsonb_array_elements(words) w
     where jsonb_typeof(answers->(w->>'id')) is distinct from 'string'
       or char_length(answers->>(w->>'id')) > 1000) then
   return scoped || '{"ok":false,"error":"invalid_answers"}';
 end if;
 insert into vocab_private.delayed_answers
 select assessment.student_code,assessment.course_id,w->>'id',a.raw,w->>'word',coalesce(w->>'category','unknown'),
   case when b.hit then 'target' when b.alt then 'accepted_alternative'
     when b.normalized='' then 'blank' else 'incorrect' end,b.hit,b.hit or b.alt
 from jsonb_array_elements(words) w
 cross join lateral (select answers->>(w->>'id') raw) a
 cross join lateral (
   select n.value normalized, n.value=vocab_private.norm(w->>'word') hit,
     n.value<>'' and exists(select from jsonb_array_elements_text(coalesce(w->'accepted','[]')) x
       where n.value=vocab_private.norm(x)) alt
   from (select vocab_private.norm(a.raw) value) n
 ) b;
 update vocab_private.delayed_tests set test_date=today,submitted_at=statement_timestamp()
   where student_code=assessment.student_code and course_id=assessment.course_id;
 return scoped || '{"status":"submitted"}';
end
$$;
revoke all on function public.vocab_delayed(jsonb) from public,anon,authenticated;
grant execute on function public.vocab_delayed(jsonb) to anon;

create function vocab_teacher.delayed(iss text, sub text, packet jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 op text := packet->>'operation';
 code text := packet->>'student';
 course text := packet->>'course';
 ver text := packet->>'version';
 ended date := (packet->>'end_date')::date;
 makeup date := (packet->>'makeup_date')::date;
 today date := (statement_timestamp() at time zone 'Asia/Taipei')::date;
 assessment vocab_private.delayed_tests%rowtype;
begin
 if not exists (select from vocab_teacher.identities i where (i.issuer,i.subject)=(iss,sub) and active) then
   raise exception 'teacher_denied';
 end if;
 if op='history' then
   return (with records as materialized (
     select d.student_code,d.course_id,d.course_version,d.practice_date,d.session_id,
       e.event_id,e.received_at,e.correct_server,w.item->>'id' word_id,e.payload->>'stage' stage,
       e.payload->>'action' action,e.payload->>'questionType' question_type,
       e.payload->>'wordAttempt' word_attempt,e.payload->>'submissionId' submission_id,
       e.payload->>'selected' selected,e.payload->>'elapsedSessionMs' elapsed_session_ms,
       case when e.payload->>'questionType'='context_cloze'
         then vocab_private.norm(e.payload->>'selected')=vocab_private.norm(w.item->>'word') end target_hit
     from vocab_private.daily d
     join vocab_teacher.resources c on (c.kind,c.name,c.issuer,c.subject)=('course',d.course_id,iss,sub)
     join vocab_teacher.resources s on (s.kind,s.name,s.issuer,s.subject)=('student',d.student_code,iss,sub)
     join vocab_private.events e using (session_id)
     join vocab_private.courses v on (v.id,v.version)=(d.course_id,d.course_version)
     join lateral (select item from jsonb_array_elements(v.document->'words') item
       where item->>'id'=e.payload->>'wordId') w on true
     where (nullif(code,'') is null or d.student_code=code)
     limit 5001
   )
   select case when count(*)>5000 then '{"overflow":true}'::jsonb
     else jsonb_build_object('events',coalesce(jsonb_agg(to_jsonb(records)),'[]')) end from records);
 end if;

 if op='read' then
   return (with tests as materialized (
     select d.*,case when d.submitted_at is not null then 'submitted'
       when today between d.end_date+8 and d.end_date+14 then 'open'
       when today=d.makeup_date then 'open_makeup'
       when today<d.end_date+8 then 'not_open' when today<d.makeup_date then 'makeup_scheduled' else 'missing' end status,
       today>d.end_date+14 and (d.submitted_at is null or d.is_makeup) as missed_regular_window
     from vocab_private.delayed_tests d
     join vocab_teacher.resources c on (c.kind,c.name,c.issuer,c.subject)=('course',d.course_id,iss,sub)
     join vocab_teacher.resources s on (s.kind,s.name,s.issuer,s.subject)=('student',d.student_code,iss,sub)
     where (nullif(course,'') is null or d.course_id=course) and (nullif(code,'') is null or d.student_code=code)
     limit 5001
   ), answers as materialized (
     select a.*,t.test_date,t.delay_days,t.course_version,t.is_makeup
     from tests t join vocab_private.delayed_answers a using(student_code,course_id) limit 5001
   )
   select case when (select count(*) from tests)>5000 or (select count(*) from answers)>5000
     then '{"overflow":true}'::jsonb else jsonb_build_object(
       'tests',coalesce((select jsonb_agg(to_jsonb(t)) from tests t),'[]'),
       'answers',coalesce((select jsonb_agg(to_jsonb(a)) from answers a),'[]')) end);
 end if;
 if not exists(select from vocab_teacher.resources where (kind,name,issuer,subject)=('course',course,iss,sub))
   or not exists(select from vocab_teacher.resources where (kind,name,issuer,subject)=('student',code,iss,sub)) then
   raise exception 'teacher_denied';
 end if;
 if op='assign' then
   if ended is null then raise exception 'invalid_delayed_date'; end if;
   insert into vocab_private.delayed_tests(student_code,course_id,course_version,end_date)
   values(code,course,ver,ended) on conflict do nothing;
   select * into assessment from vocab_private.delayed_tests where (student_code,course_id)=(code,course);
   if (assessment.end_date,assessment.course_version) is distinct from (ended,ver) then raise exception 'delayed_assignment_conflict'; end if;
 elsif op='makeup' then
   update vocab_private.delayed_tests set makeup_date=makeup
     where (student_code,course_id)=(code,course) and submitted_at is null
       and makeup>=today and makeup>end_date+14;
   if not found then raise exception 'invalid_delayed_date'; end if;
 else raise exception 'invalid_operation';
 end if;
 insert into vocab_teacher.audit(issuer,subject,action,resource) values(iss,sub,'delayed_'||op,course);
 return 'true';
end
$$;
revoke all on function vocab_teacher.delayed(text,text,jsonb) from public,anon,authenticated;
grant execute on function vocab_teacher.delayed(text,text,jsonb) to vocab_teacher_runtime;
notify pgrst,'reload schema';
commit;
