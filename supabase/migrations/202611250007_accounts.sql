begin;
create table vocab_teacher.account_operators (
  issuer text not null, subject text not null, primary key(issuer,subject),
  foreign key(issuer,subject) references vocab_teacher.identities(issuer,subject)
);
create table vocab_teacher.question_invites (
  email text primary key, subject text unique, created_at timestamptz not null default now()
);
create table vocab_teacher.student_classes (
  student_code text primary key references vocab_private.students(code),
  class_name text not null check (char_length(class_name) between 1 and 80)
);
alter table vocab_teacher.account_operators enable row level security;
alter table vocab_teacher.question_invites enable row level security;
alter table vocab_teacher.student_classes enable row level security;
revoke all on vocab_teacher.account_operators,vocab_teacher.question_invites,vocab_teacher.student_classes from public,anon,authenticated,vocab_teacher_runtime;

create function vocab_teacher.enroll_question_teacher(iss text, sub text, verified_email text) returns boolean
language plpgsql security definer set search_path='' as $$
declare existing text;
begin
 if iss is distinct from 'https://accounts.google.com' or coalesce(sub,'') !~ '^[0-9]{10,30}$' then return false; end if;
 select i.subject into existing from vocab_teacher.question_invites i where i.email=lower(verified_email) for update;
 if not found then return false; end if;
 if existing is not null then return existing=sub; end if;
 if exists (select from vocab_teacher.identities i where (i.issuer,i.subject)=(iss,sub)) then return false; end if;
 insert into vocab_teacher.identities(issuer,subject,active) values(iss,sub,true);
 update vocab_teacher.question_invites set subject=sub where email=lower(verified_email);
 return true;
end
$$;

alter function vocab_teacher.request(text,text,text,jsonb) rename to request_before_accounts;
revoke all on function vocab_teacher.request_before_accounts(text,text,text,jsonb) from public,anon,authenticated,vocab_teacher_runtime;
create function vocab_teacher.request(teacher_issuer text, teacher_subject text, operation text, packet jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
begin
 if teacher_issuer='https://accounts.google.com' and exists (
   select from vocab_teacher.question_invites i where i.subject=teacher_subject
 ) and operation not in ('authorize','list','read','save','course','versions','can_manage_version','visibility') then
   raise exception 'teacher_denied';
 end if;
 return vocab_teacher.request_before_accounts(teacher_issuer,teacher_subject,operation,packet);
end
$$;

create function vocab_teacher.manage_accounts(iss text, sub text, op text, packet jsonb)
returns jsonb language plpgsql security definer set search_path='' as $$
declare item jsonb;
 email_value text := lower(btrim(packet->>'email'));
 input_code text;
 input_class text;
begin
 if not exists (select from vocab_teacher.account_operators a join vocab_teacher.identities i using(issuer,subject)
   where (a.issuer,a.subject)=(iss,sub) and i.active) then raise exception 'teacher_denied'; end if;
 if op='authorize' then return 'true'; end if;
 if op='list' then
   return jsonb_build_object(
    'teachers',coalesce((select jsonb_agg(to_jsonb(q)) from (
      select i.email,case when i.subject is null then '待首次登入' else '已啟用' end status
      from vocab_teacher.question_invites i order by i.email limit 500) q),'[]'),
    'students',coalesce((select jsonb_agg(to_jsonb(q)) from (
      select c.class_name,s.code as student_code from vocab_teacher.student_classes c
      join vocab_private.students s on s.code=c.student_code order by c.class_name,s.code limit 500) q),'[]'));
 elsif op='invite' then
   if coalesce(email_value,'') !~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$' or length(email_value)>254 then
     raise exception 'invalid_invite';
   end if;
   insert into vocab_teacher.question_invites(email) values (email_value) on conflict do nothing;
   insert into vocab_teacher.audit(issuer,subject,action,resource) values(iss,sub,'question_teacher_invite','');
   return 'true';
 elsif op='import_students' then
   if jsonb_typeof(packet->'students') is distinct from 'array' then raise exception 'invalid_student_file'; end if;
   if jsonb_array_length(packet->'students') not between 1 and 500 then raise exception 'invalid_student_file'; end if;
   for item in select value from jsonb_array_elements(packet->'students') loop
     input_code := item->>'student_code';
     input_class := btrim(item->>'class_name');
     if coalesce(input_code,'') !~ '^[A-Za-z0-9_-]{3,32}$' or coalesce(char_length(input_class),0) not between 1 and 80 then
       raise exception 'invalid_student_file';
     end if;
     if exists (select from vocab_private.students s where s.code=input_code) then raise exception 'student_already_exists'; end if;
     perform vocab_private.register_student(input_code,item->>'password');
     insert into vocab_teacher.student_classes values (input_code,input_class);
     insert into vocab_teacher.resources values ('student',input_code,iss,sub);
   end loop;
   insert into vocab_teacher.audit(issuer,subject,action,resource)
     values(iss,sub,'student_csv_import',jsonb_array_length(packet->'students')::text);
   return to_jsonb(jsonb_array_length(packet->'students'));
 end if;
 raise exception 'invalid_operation';
exception when unique_violation then raise exception 'student_already_exists';
end
$$;

create function public.vocab_change_password(packet jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare ack jsonb;
 new_password text := packet->>'newPassword';
begin
 perform 1 from vocab_private.students where code=packet->>'studentCode' and active for no key update;
 ack := vocab_private.vocab_request_v1(packet || '{"operation":"daily_status","courseId":"account"}');
 if ack->>'ok' is distinct from 'true' then return ack; end if;
 ack := jsonb_build_object('ok',true,'requestId',packet->>'requestId','protocol','supabase-v1','appVersion','0.3.11');
 if new_password is null or char_length(new_password)<8 or octet_length(new_password)>72
    or btrim(new_password)='' or new_password=packet->>'pin' then
   return ack || '{"ok":false,"error":"invalid_new_password"}';
 end if;
 update vocab_private.students set pin_hash=extensions.crypt(new_password,extensions.gen_salt('bf',10))
   where code=packet->>'studentCode' and active;
 return ack;
end
$$;

revoke all on function vocab_teacher.enroll_question_teacher(text,text,text),vocab_teacher.request(text,text,text,jsonb),vocab_teacher.manage_accounts(text,text,text,jsonb),public.vocab_change_password(jsonb) from public,anon,authenticated;
grant execute on function vocab_teacher.enroll_question_teacher(text,text,text),vocab_teacher.request(text,text,text,jsonb),vocab_teacher.manage_accounts(text,text,text,jsonb) to vocab_teacher_runtime;
grant execute on function public.vocab_change_password(jsonb) to anon;
notify pgrst,'reload schema';
commit;
