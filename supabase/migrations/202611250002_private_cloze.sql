begin;
alter function public.vocab_request(jsonb) set schema vocab_private;
alter function vocab_private.vocab_request(jsonb) rename to vocab_request_v1;
revoke all on function vocab_private.vocab_request_v1(jsonb) from public, anon, authenticated;

create function public.vocab_request(packet jsonb) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare
  reply jsonb;
  words jsonb;
  answers jsonb := packet->'answers';
  graded jsonb;
begin
  if packet->>'operation' is distinct from 'grade_cloze' then
    return vocab_private.vocab_request_v1(packet);
  end if;
  if octet_length(packet::text) > 240000 or jsonb_typeof(answers) is distinct from 'object' then
    return jsonb_build_object('ok',false,'error','invalid_answers','requestId',packet->>'requestId',
      'protocol','supabase-v1','appVersion','0.3.11');
  end if;
  reply := vocab_private.vocab_request_v1(packet || '{"operation":"daily_status"}');
  if reply->>'ok' is distinct from 'true' then return reply; end if;
  if reply->>'status' is distinct from 'in_progress' or coalesce(reply->>'sessionId','') = ''
      or reply->>'courseVersion' is distinct from packet->>'courseVersion' then
    return reply || '{"ok":false,"error":"daily_session_mismatch"}';
  end if;
  select document->'words' into words from vocab_private.courses
    where id=packet->>'courseId' and version=reply->>'courseVersion' and active;
  if not found then return reply || '{"ok":false,"error":"course_not_active"}'; end if;
  if (select count(*) from jsonb_object_keys(answers)) <> jsonb_array_length(words)
    or exists (select 1 from jsonb_array_elements(words) w
               where jsonb_typeof(answers->(w->>'id')) is distinct from 'string'
                  or vocab_private.norm(answers->>(w->>'id')) = '') then
    return reply || '{"ok":false,"error":"invalid_answers"}';
  end if;
  select jsonb_object_agg(w->>'id',
    vocab_private.norm(answers->>(w->>'id')) = vocab_private.norm(w->>'word')
    or exists (select 1 from jsonb_array_elements_text(coalesce(w->'accepted','[]'::jsonb)) a
               where vocab_private.norm(a)=vocab_private.norm(answers->>(w->>'id'))))
    into graded from jsonb_array_elements(words) w;
  return reply || jsonb_build_object('grades',graded);
end
$$;
revoke all on function public.vocab_request(jsonb) from public, anon, authenticated;
grant execute on function public.vocab_request(jsonb) to anon;
notify pgrst, 'reload schema';
commit;
