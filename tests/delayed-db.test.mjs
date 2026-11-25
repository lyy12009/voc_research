import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, test } from 'node:test';
import { fixture, seed } from './fixture.mjs';

let db, day;
const pin='synthetic-pin';
const scoped=(packet,subject='teacher-A')=>db.query('select vocab_teacher.delayed($1,$2,$3) as r',
  ['https://issuer.test',subject,packet]).then(result=>result.rows[0].r);
const rpc=(studentCode,operation,extras={})=>db.query('select public.vocab_delayed($1) as r',[{
  operation,protocol:'supabase-v1',requestId:randomUUID(),studentCode,pin,courseId:'IT_DELAY',courseVersion:'v1',...extras,
}]).then(result=>result.rows[0].r);
const offset=days=>new Date(Date.parse(day+'T00:00:00Z')+days*86400000).toISOString().slice(0,10);
const assign=(student,days)=>scoped({operation:'assign',student,course:'IT_DELAY',version:'v1',end_date:offset(-days)});

before(async()=>{
  db=await fixture();
  for(const code of ['IT_D8','IT_D14','IT_EARLY','IT_MISSING','IT_MAKEUP','IT_UNASSIGNED'])
    await seed(db,'IT_DELAY',code,pin);
  day=(await db.query("select (statement_timestamp() at time zone 'Asia/Taipei')::date::text as day")).rows[0].day;
});
after(async()=>{await db?.close();});

test('day 8 to 14 and absence are distinct; students have separate eligibility',async()=>{
  for(const [student,days,status] of [['IT_D8',8,'open'],['IT_D14',14,'open'],
    ['IT_EARLY',7,'not_open'],['IT_MISSING',15,'missing'],['IT_MAKEUP',17,'missing']]){
    assert.equal(await assign(student,days),true);
    assert.equal((await rpc(student,'delayed_status')).status,status);
  }
  assert.equal((await rpc('IT_UNASSIGNED','delayed_status')).status,'not_assigned');
  assert.equal((await rpc('IT_D8','delayed_status',{pin:'bad-pin-for-test'})).ok,false);
  assert.equal((await scoped({operation:'read'})).answers.length,0);
});

test('one atomic first submission across concurrent attempts and versions preserves raw answer types',async()=>{
  let wrong=await rpc('IT_D8','delayed_submit',{courseVersion:'v2',answers:{W1:'先修詞',W2:'乙'}});
  assert.equal(wrong.error,'version_mismatch');
  assert.equal((await rpc('IT_D8','delayed_submit',{answers:{W1:'broken'}})).error,'invalid_answers');
  const finished=await Promise.all([
    rpc('IT_D8','delayed_submit',{answers:{W1:' 先修詞。 ',W2:'乙'}}),
    rpc('IT_D8','delayed_submit',{answers:{W1:'甲',W2:'never overwrite'}}),
  ]);
  assert.ok(finished.every(r=>r.status==='submitted'&&!Object.hasOwn(r,'grades')));
  const saved=(await scoped({operation:'read',student:'IT_D8'}));
  assert.equal(saved.tests[0].delay_days,8);
  assert.equal(saved.tests[0].is_makeup,false);
  assert.equal(saved.tests[0].test_date,day);
  assert.deepEqual(saved.answers.sort((a,b)=>a.word_id.localeCompare(b.word_id))
    .map(a=>[a.actual_answer,a.answer_type,a.target_hit,a.correct_server]),
    [[' 先修詞。 ','accepted_alternative',false,true],['乙','target',true,true]]);
  const rows=await db.query('select count(*)::int n from vocab_private.daily');
  assert.equal(rows.rows[0].n,0);
});

test('makeup requires teacher scope and remains marked separately',async()=>{
  const packet={operation:'makeup',student:'IT_MAKEUP',course:'IT_DELAY',makeup_date:day};
  await assert.rejects(scoped(packet,'teacher-B'),/teacher_denied/);
  assert.deepEqual(await scoped({operation:'read'},'teacher-B'),{tests:[],answers:[]});
  assert.deepEqual(await scoped({operation:'history'},'teacher-B'),{events:[]});
  await db.exec('set role anon');
  try{
    await assert.rejects(scoped({operation:'read'}),/permission denied/i);
    await assert.rejects(db.query('select * from vocab_private.delayed_answers'),/permission denied/i);
  }finally{await db.exec('reset role');}
  assert.equal(await scoped(packet),true);
  assert.equal((await rpc('IT_MAKEUP','delayed_status')).status,'open_makeup');
  assert.equal((await rpc('IT_MAKEUP','delayed_submit',{answers:{W1:'',W2:'錯'}})).status,'submitted');
  const saved=await scoped({operation:'read',student:'IT_MAKEUP'});
  assert.equal(saved.tests[0].delay_days,17);
  assert.equal(saved.tests[0].is_makeup,true);
  assert.deepEqual(new Set(saved.answers.map(row=>row.answer_type)),new Set(['blank','incorrect']));
  assert.equal((await scoped({operation:'read',student:'IT_MISSING'})).tests[0].status,'missing');
  assert.equal((await scoped({operation:'read',student:'IT_MISSING'})).answers.length,0);
});
