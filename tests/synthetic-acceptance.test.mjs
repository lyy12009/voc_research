import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { delimiter } from 'node:path';
import test from 'node:test';
import { generate, openSynthetic, readStudy, scope } from './synthetic-study.mjs';

test('20-student synthetic history reconciles SQL, dashboard and CSV/Excel', {timeout:120000},async t=>{
  const {db,data}=await openSynthetic();
  t.after(()=>db.close());
  assert.deepEqual(generate(),data);
  assert.equal(data.students.length,20);
  assert.deepEqual(data.courses.map(c=>c.words.length),[37,26,36,32,30]);
  assert.ok((Date.parse(data.tests.at(-1).test_date)-Date.parse(data.sessions[0].practice_date))/86400000>=28);
  const metadata=await readStudy(db,'metadata',scope);
  assert.equal(metadata.students.length,20);
  assert.deepEqual(await readStudy(db,'metadata',scope,'teacher-B'),{students:[],words:[]});
  const query=await readStudy(db,'research',scope);
  const allHistory=await readStudy(db,'delayed',{operation:'history'});
  assert.equal(query.overflow,true);
  assert.equal(allHistory.overflow,true);
  const parts={},history={};
  for(const student of metadata.students){
    parts[student]=await readStudy(db,'research',{...scope,student});
    history[student]=await readStudy(db,'delayed',{operation:'history',student});
  }
  const delayed=await readStudy(db,'delayed',{operation:'read'});
  const {rows:[stored]}=await db.query(`select
    (select count(*)::int from vocab_private.events) events,
    (select count(*)::int from vocab_private.daily) sessions,
    (select count(*)::int from vocab_private.daily where completed_at is null) interrupted,
    (select count(*)::int from vocab_private.delayed_tests where test_date is null) missed,
    (select count(*)::int from vocab_private.delayed_tests where is_makeup) makeup,
    (select count(*)::int from vocab_private.delayed_answers where target_hit) target,
    (select count(*)::int from vocab_private.delayed_answers where correct_server) acceptable,
    (select count(*)::int from vocab_private.delayed_answers) items`);
  assert.equal(stored.events,data.events.length,'replayed IDs did not increase row count');
  assert.equal(new Set(Object.values(parts).flatMap(p=>p.events.map(e=>e.event_id))).size,stored.events);
  assert.equal(stored.sessions,data.sessions.length);
  assert.ok(stored.interrupted>0 && stored.missed>0 && stored.makeup>0 && stored.acceptable>stored.target);
  assert.ok(delayed.tests.every(r=>r.delay_days===null || r.delay_days===17 ||
    (r.delay_days>=8&&r.delay_days<=14)));
  assert.ok(Object.values(parts).some(p=>p.sessions.some(r=>r.course_version==='v2')));
  const result=spawnSync(process.env.VOCAB_PYTHON||'python',['tests/study_acceptance.py'],{
    input:JSON.stringify({scope,metadata,parts,history,delayed,stored}),
    encoding:'utf8',maxBuffer:10_000_000,
    env:{...process.env,PYTHONPATH:[process.cwd(),process.env.PYTHONPATH].filter(Boolean).join(delimiter)},
  });
  assert.equal(result.status,0,result.stderr||result.stdout);
  t.diagnostic(result.stdout.trim());
});
