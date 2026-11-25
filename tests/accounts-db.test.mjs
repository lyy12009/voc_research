import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { fixture, teacher } from './fixture.mjs';
let db;
const iss='https://accounts.google.com', admin='11111111111', other='22222222222';
const sql=(q,params)=>db.query(q,params).then(r=>r.rows[0].r);
const manage=(operation,packet={},subject=admin)=>sql('select vocab_teacher.manage_accounts($1,$2,$3,$4) r',[iss,subject,operation,packet]);
const enrollment=(sub,email)=>sql('select vocab_teacher.enroll_question_teacher($1,$2,$3) r',[iss,sub,email]);
const item=(student_code,password='fixture-old-01')=>({class_name:'合成一班',student_code,password});
const packet=(pin,password)=>({operation:'change_password',protocol:'supabase-v1',requestId:'fixture',
  studentCode:'00123',pin,newPassword:password});
before(async()=>{
  db=await fixture();
  await db.query('insert into vocab_teacher.identities values ($1,$2,true);',[iss,admin]);
  await db.query('insert into vocab_teacher.account_operators values ($1,$2);',[iss,admin]);
});
after(async()=>{await db?.close()});
test('only an invited subject can enroll; invited teachers cannot manage student accounts',async()=>{
  assert.equal(await enrollment(other,'test@example.test'),false);
  assert.equal(await manage('invite',{email:'Test@example.test'}),true);
  assert.equal(await enrollment(other,'test@example.test'),true);
  assert.equal(await enrollment('33333333333','test@example.test'),false);
  assert.equal(await sql('select vocab_teacher.request($1,$2,$3,$4) r',[iss,other,'authorize',{}]),true);
  await assert.rejects(manage('list',{},other),/teacher_denied/);
  await assert.rejects(sql('select vocab_teacher.request($1,$2,$3,$4) r',[iss,other,'student',{}]),/teacher_denied/);
  await assert.rejects(sql('select vocab_teacher.request($1,$2,$3,$4) r',[iss,other,'practice',{}]),/teacher_denied/);
});
test('CSV import is atomic and omits passwords from listing',async()=>{
  assert.equal(await manage('import_students',{students:[item('00123')]}),1);
  await assert.rejects(manage('import_students',{students:[item('00124'),item('00123','never-replace')]}),/student_already_exists/);
  const out=await manage('list');
  assert.deepEqual(out.students,[{class_name:'合成一班',student_code:'00123'}]);
  assert.ok(!JSON.stringify(out).includes('fixture-old'));
  await db.exec('set role anon');
  try{
    await assert.rejects(manage('list'),/permission denied/i);
    await assert.rejects(db.query('select * from vocab_teacher.student_classes'),/permission denied/i);
  }finally{await db.exec('reset role')}
});
test('student changes password with the previous password once and keeps the same identifier',async()=>{
  assert.equal((await sql('select public.vocab_change_password($1) r',[packet('bad-fixture','fixture-new-01')])).ok,false);
  const change=(password)=>sql('select public.vocab_change_password($1) r',[packet('fixture-old-01',password)]);
  const [a,b]=await Promise.all([change('fixture-new-01'),change('fixture-new-02')]);
  assert.equal([a,b].filter(x=>x.ok).length,1);
  const pin=a.ok?'fixture-new-01':'fixture-new-02';
  const signIn=(pin)=>sql('select public.vocab_request($1) r',[{operation:'daily_status',protocol:'supabase-v1',
    courseId:'fixture',studentCode:'00123',pin}]);
  assert.equal((await signIn('fixture-old-01')).ok,false);
  assert.equal((await signIn(pin)).ok,true);
  assert.equal((await manage('list')).students[0].student_code,'00123');
});
