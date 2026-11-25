
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, test } from 'node:test';
import { fixture, seed, teacher } from './fixture.mjs';

let db, today, sessionId;
const code='IT_RESEARCH_S', course='IT_RESEARCH_C', pin='synthetic-only';
const scoped=(subject, filters)=>db.query('select vocab_teacher.research($1,$2,$3) result',
  ['https://issuer.test', subject, filters]).then(r=>r.rows[0].result);
const request=(operation, extra={})=>db.query('select public.vocab_request($1) result', [{
  protocol:'supabase-v1', requestId:randomUUID(), operation, studentCode:code, pin, courseId:course, courseVersion:'v1', ...extra,
}]).then(r=>r.rows[0].result);
const range=()=>({from:today,to:today});
before(async()=>{
  db=await fixture();
  await seed(db,course,code,pin);
  await teacher(db,'course',{document:{id:'IT_UNUSED',version:'v1',words:[
    {id:'W99',word:'合成詞',meanings:{en:'synthetic'},accepted:['替代'],category:'topic'}
  ]},manifest:{}});
  today=(await request('daily_status')).practiceDate;
  sessionId=randomUUID();
  assert.equal((await request('daily_start',{sessionId,practiceDate:today})).status,'in_progress');
  for(const [index,selected] of ['錯誤','先修詞','甲'].entries()){
    const event={eventId:randomUUID(), studentCode:code, courseId:course, courseVersion:'v1', practiceDate:today,
      sessionId, study:'vocab', mode:'practice', stage:'cloze', action:'answer', questionType:'context_cloze',
      selected, wordId:'W1', round:index+1, wordAttempt:index+1, submissionId:randomUUID(),
      firstAttempt:index===0, elapsedSessionMs:(index+1)*1000};
    assert.equal((await request('events',{events:[event]})).ok,true);
  }
});
after(async()=>{ await db?.close(); });

test('research scope is checked for student and course; anonymous and unlisted are denied',async()=>{
  await assert.rejects(scoped('nobody',range()),/teacher_denied/);
  assert.deepEqual(await scoped('teacher-B',range()),{events:[],sessions:[],words:[]});
  await db.exec('set role anon');
  try { await assert.rejects(scoped('teacher-A',range()),/permission denied/); }
  finally { await db.exec('reset role'); }
  await db.exec('set role vocab_teacher_runtime');
  try {
    assert.deepEqual(await scoped('teacher-A',{...range(),student:'other'}),{events:[],sessions:[],words:[]});
    assert.equal((await scoped('teacher-A',range())).sessions.length,1);
  } finally { await db.exec('reset role'); }
});

test('raw output preserves each input, server correctness, target hit and legacy unknown category',async()=>{
  const result=await scoped('teacher-A',{...range(),course,word:'W1',category:'unknown'});
  assert.equal(result.sessions.length,1);
  assert.equal(result.sessions[0].completed_at,null);
  const sorted=result.events.sort((a,b)=>Number(a.word_attempt)-Number(b.word_attempt));
  assert.deepEqual(sorted.map(e=>[e.selected,e.correct_server,e.target_hit]),[
    ['錯誤',false,false],['先修詞',true,false],['甲',true,true],
  ]);
  assert.ok(result.words.some(word=>word.accepted.includes('先修詞')));
  assert.deepEqual(sorted.map(event=>event.elapsed_session_ms),['1000','2000','3000']);
  assert.equal(new Set(sorted.map(event=>event.submission_id)).size,3);
  const unused=await scoped('teacher-A',{...range(),course:'IT_UNUSED',category:'topic'});
  assert.equal(unused.sessions.length,0);
  assert.equal(unused.words[0].target_word,'合成詞');
});

test('daily practice RPC refuses delayed-mode records',async()=>{
  const eventId=randomUUID();
  const event={eventId, studentCode:code, courseId:course, courseVersion:'v1', practiceDate:today,
    sessionId, study:'vocab', mode:'delayed', stage:'cloze', action:'answer', questionType:'context_cloze',
    selected:'甲', wordId:'W1', round:1, wordAttempt:1, submissionId:randomUUID()};
  assert.equal((await request('events',{events:[event]})).ok,false);
  const result=await scoped('teacher-A',range());
  assert.ok(result.events.every(event=>event.mode==='practice'&&event.event_id!==eventId));
});

test('research range and overflow prevent partial statistics',async()=>{
  await assert.rejects(scoped('teacher-A',{from:'2020-01-01',to:today}),/invalid_date_range/);
  await db.query("insert into vocab_private.events (event_id,session_id,payload) select 'synthetic-'||n,$1,'{}' from generate_series(1,5001) n",[sessionId]);
  assert.deepEqual(await scoped('teacher-A',range()),{overflow:true});
});
