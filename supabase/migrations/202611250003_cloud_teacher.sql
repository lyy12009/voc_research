begin;
create role vocab_teacher_runtime nologin;
create schema vocab_teacher;
revoke all on schema vocab_teacher from public, anon, authenticated;
grant usage on schema vocab_teacher to vocab_teacher_runtime;

create table vocab_teacher.identities (
  issuer text not null, subject text not null, active boolean not null default true,
  primary key (issuer, subject)
);
create table vocab_teacher.documents (
  issuer text not null, subject text not null, kind text not null, name text not null,
  revision int not null, document jsonb not null, created_at timestamptz not null default now(),
  primary key (issuer, subject, kind, name, revision),
  foreign key (issuer, subject) references vocab_teacher.identities
);
create table vocab_teacher.resources (
  kind text not null, name text not null, issuer text not null, subject text not null,
  primary key (kind, name),
  foreign key (issuer, subject) references vocab_teacher.identities
);
create table vocab_teacher.publications (
  course text not null, version text not null, manifest jsonb not null,
  primary key (course, version)
);
create table vocab_teacher.audit (
  recorded_at timestamptz not null default now(), issuer text not null, subject text not null,
  action text not null, resource text not null
);
alter table vocab_teacher.identities enable row level security;
alter table vocab_teacher.documents enable row level security;
alter table vocab_teacher.resources enable row level security;
alter table vocab_teacher.publications enable row level security;
alter table vocab_teacher.audit enable row level security;
revoke all on all tables in schema vocab_teacher from public, anon, authenticated, vocab_teacher_runtime;

create function vocab_teacher.request(teacher_issuer text, teacher_subject text, operation text, packet jsonb)
returns jsonb language plpgsql security definer set search_path = '' as $body$
declare
  kind_arg text := packet->>'kind';
  name_arg text := packet->>'name';
  doc jsonb := packet->'document';
  current_doc jsonb;
  current_revision int;
  result jsonb;
  course_version text := doc->>'version';
begin
  if not exists (select from vocab_teacher.identities i
    where i.issuer = teacher_issuer and i.subject = teacher_subject and i.active) then
    raise exception 'teacher_denied';
  end if;
  if operation = 'authorize' then return 'true'; end if;

  if operation in ('list', 'read', 'save') then
    if coalesce(kind_arg, '') not in ('book','draft') then raise exception 'invalid_kind'; end if;
    if operation = 'list' then
      return coalesce((select jsonb_agg(names.name order by names.name) from (
        select distinct d.name from vocab_teacher.documents d where d.issuer = teacher_issuer
          and d.subject = teacher_subject and d.kind = kind_arg order by d.name limit 500
      ) names), '[]');
    end if;
    if coalesce(name_arg, '') !~ '^[A-Za-z0-9_.-]{1,90}$' then raise exception 'invalid_name'; end if;
    if operation = 'save' then
      perform pg_advisory_xact_lock(hashtextextended(jsonb_build_array(teacher_issuer,teacher_subject,kind_arg,name_arg)::text, 0));
    end if;
    select d.revision, d.document into current_revision, current_doc
      from vocab_teacher.documents d where d.issuer = teacher_issuer and d.subject = teacher_subject
      and d.kind = kind_arg and d.name = name_arg order by d.revision desc limit 1;
    if operation = 'read' then
      return jsonb_build_object('revision', coalesce(current_revision,0), 'document', current_doc);
    end if;
    if doc is null or octet_length(doc::text) > 2500000
      or jsonb_typeof(doc) is distinct from (case when kind_arg = 'book' then 'array' else 'object' end) then
      raise exception 'invalid_document';
    end if;
    if current_doc = doc then return to_jsonb(current_revision); end if;
    if coalesce(current_revision,0) is distinct from (packet->>'expected')::int then raise exception 'revision_conflict'; end if;
    current_revision := coalesce(current_revision,0) + 1;
    insert into vocab_teacher.documents values (teacher_issuer, teacher_subject, kind_arg, name_arg, current_revision, doc);
    result := to_jsonb(current_revision);
  elsif operation in ('course', 'student') then
    name_arg := case when operation = 'course' then doc->>'id' else packet->>'code' end;
    if coalesce(name_arg,'') !~ '^[A-Za-z0-9_.-]{1,90}$' then raise exception 'invalid_name'; end if;
    perform pg_advisory_xact_lock(hashtextextended(jsonb_build_array(operation,name_arg)::text, 0));
    if not exists (select from vocab_teacher.resources r where r.kind=operation and r.name=name_arg
      and r.issuer=teacher_issuer and r.subject=teacher_subject) then
      if exists (select from vocab_teacher.resources r where r.kind=operation and r.name=name_arg)
        or (operation='course' and exists (select from vocab_private.courses c where c.id=name_arg))
        or (operation='student' and exists (select from vocab_private.students s where s.code=name_arg)) then
        raise exception 'resource_conflict';
      end if;
      insert into vocab_teacher.resources values (operation,name_arg,teacher_issuer,teacher_subject);
    end if;
    if operation = 'course' then
      if jsonb_typeof(packet->'manifest') is distinct from 'object' then raise exception 'invalid_manifest'; end if;
      select c.document into current_doc from vocab_private.courses c where c.id=name_arg and c.version=course_version and c.active;
      if not found then
        perform vocab_private.register_course(doc);
        insert into vocab_teacher.publications values (name_arg,course_version,packet->'manifest');
      elsif current_doc is distinct from doc or not exists (
        select from vocab_teacher.publications p where p.course=name_arg and p.version=course_version and p.manifest=packet->'manifest'
      ) then raise exception 'publication_conflict';
      else return 'true';
      end if;
    else
      if exists (select from vocab_private.students s where s.code=name_arg and s.active
        and s.pin_hash=extensions.crypt(packet->>'pin',s.pin_hash)) then return 'true'; end if;
      if exists (select from vocab_private.students s where s.code=name_arg) then raise exception 'resource_conflict'; end if;
      perform vocab_private.register_student(name_arg,packet->>'pin');
    end if;
    result := 'true';
  elsif operation in ('visibility','can_manage_version') then
    if not exists (select from vocab_teacher.resources r join vocab_teacher.publications p on p.course=r.name
      where r.kind='course' and r.name=name_arg and p.version=packet->>'version' and p.manifest->>'branch'=packet->>'branch'
        and r.issuer=teacher_issuer and r.subject=teacher_subject) then raise exception 'teacher_denied'; end if;
    if operation='can_manage_version' then return 'true'; end if;
    result := 'true';
  elsif operation in ('versions','practice','answers') then
    if operation = 'versions' then
      select jsonb_agg(to_jsonb(x)) into result from (
        select c.id,c.version,c.active,c.document->>'title' as title from vocab_private.courses c
        join vocab_teacher.resources r on r.kind='course' and r.name=c.id
        where r.issuer=teacher_issuer and r.subject=teacher_subject order by c.id,c.version limit 200
      ) x;
    elsif operation = 'practice' then
      select jsonb_agg(to_jsonb(x)) into result from (
        select d.student_code,d.course_id,d.course_version,d.practice_date,d.session_id,d.completed_at,
          (select count(*) from vocab_private.events e where e.session_id=d.session_id and e.correct_server is false) as incorrect_answers
        from vocab_private.daily d
        join vocab_teacher.resources r on r.kind='course' and r.name=d.course_id
        join vocab_teacher.resources s on s.kind='student' and s.name=d.student_code
        where r.issuer=teacher_issuer and r.subject=teacher_subject and s.issuer=teacher_issuer and s.subject=teacher_subject
        order by d.practice_date desc,d.started_at desc limit 200
      ) x;
    else
      select jsonb_agg(to_jsonb(x)) into result from (
        select e.event_id,e.received_at,e.correct_server,e.payload->>'wordId' as word_id,
          e.payload->>'selected' as selected,case when e.payload->>'questionType'='context_cloze'
            then vocab_private.norm(e.payload->>'selected')=vocab_private.norm(w.item->>'word') end as target_answer
        from vocab_private.events e join vocab_private.daily d using(session_id)
        join vocab_private.courses c on c.id=d.course_id and c.version=d.course_version
        left join lateral (select item from jsonb_array_elements(c.document->'words') item
          where item->>'id'=e.payload->>'wordId') w on true
        join vocab_teacher.resources r on r.kind='course' and r.name=d.course_id
        join vocab_teacher.resources s on s.kind='student' and s.name=d.student_code
        where d.session_id=name_arg and r.issuer=teacher_issuer and r.subject=teacher_subject
          and s.issuer=teacher_issuer and s.subject=teacher_subject
        order by e.received_at desc,e.event_id limit 500
      ) x;
    end if;
    result := coalesce(result,'[]');
  else raise exception 'invalid_operation';
  end if;
  insert into vocab_teacher.audit (issuer,subject,action,resource)
    values (teacher_issuer,teacher_subject,operation,coalesce(name_arg,''));
  return result;
end
$body$;
revoke all on function vocab_teacher.request(text,text,text,jsonb) from public, anon, authenticated;
grant execute on function vocab_teacher.request(text,text,text,jsonb) to vocab_teacher_runtime;
commit;
