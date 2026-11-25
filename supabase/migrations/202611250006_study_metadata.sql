begin;
create function vocab_teacher.study_metadata(iss text, sub text, packet jsonb) returns jsonb
language plpgsql stable security definer set search_path='' as $$
begin
 if not exists (select from vocab_teacher.identities i where (i.issuer,i.subject)=(iss,sub) and i.active) then
   raise exception 'teacher_denied';
 end if;
 return (with roster as materialized (
   select r.name from vocab_teacher.resources r where
     (r.kind,r.issuer,r.subject)=('student',iss,sub)
     and (nullif(packet->>'student','') is null or r.name=packet->>'student')
   order by r.name limit 101
 ), words as materialized (
   select v.id course_id,v.version course_version,w.item->>'id' word_id,
     nullif(btrim(w.item->>'part_of_speech'),'') part_of_speech,
     w.item->>'word' target_word, coalesce(w.item->>'category','unknown') category, w.item->'accepted' accepted
   from vocab_private.courses v
   join vocab_teacher.resources r on (r.kind,r.name,r.issuer,r.subject)=('course',v.id,iss,sub)
   cross join lateral jsonb_array_elements(v.document->'words') w(item)
   where nullif(packet->>'course','') is null or v.id=packet->>'course'
   limit 5001
 )
 select case when (select count(*) from roster)>100 or (select count(*) from words)>5000 then '{"overflow":true}'::jsonb
   else jsonb_build_object('students',coalesce((select jsonb_agg(name) from roster),'[]'),
     'words',coalesce((select jsonb_agg(to_jsonb(w)) from words w),'[]')) end);
end
$$;
revoke all on function vocab_teacher.study_metadata(text,text,jsonb) from public,anon,authenticated;
grant execute on function vocab_teacher.study_metadata(text,text,jsonb) to vocab_teacher_runtime;
commit;
