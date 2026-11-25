import assert from 'node:assert/strict';
import { after, before, test } from 'node:test';
import { fixture, seed, teacher } from './fixture.mjs';

let db;
before(async()=>{ db=await fixture(); });
after(async()=>{ await db?.close(); });

test('anon and authenticated cannot use teacher authorization or access teacher documents', async()=>{
  for(const role of ['anon','authenticated']) {
    await db.exec('set role '+role);
    try{
      await assert.rejects(teacher(db,'authorize'),/permission denied/);
      await assert.rejects(db.query('select * from vocab_teacher.documents'),/permission denied/);
    } finally { await db.exec('reset role'); }
  }
});

test('restricted role can run only the scoped bridge',async()=>{
  await db.exec('set role vocab_teacher_runtime');
  try {
    assert.equal(await teacher(db,'authorize'),true);
    await assert.rejects(teacher(db,'authorize',{},'unlisted'),/teacher_denied/);
    await assert.rejects(db.query('select * from vocab_teacher.documents'),/permission denied/);
    await assert.rejects(db.query('select * from vocab_private.students'),/permission denied/);
  } finally { await db.exec('reset role'); }
});

test('draft saves are revisioned, scoped, retriable and reject stale edits',async()=>{
  const base={kind:'draft',name:'sample'};
  const request={...base,expected:0,document:{rows:[{accepted:['先修詞']}]}};
  assert.equal(await teacher(db,'save',request),1);
  assert.equal(await teacher(db,'save',request),1);
  assert.equal(await teacher(db,'save',{...request,expected:1,document:{rows:[]}}),2);
  await assert.rejects(teacher(db,'save',request),/revision_conflict/);
  assert.deepEqual(await teacher(db,'read',base),{revision:2,document:{rows:[]}});
  assert.deepEqual(await teacher(db,'read',base,'teacher-B'),{revision:0,document:null});
  assert.deepEqual(await teacher(db,'list',{kind:'draft'},'teacher-B'),[]);
});

test('synthetic student and private course registration are safely retriable and audited',async()=>{
  await seed(db,'IT_A','IT_X','fixture-pin');
  await seed(db,'IT_A','IT_X','fixture-pin');
  assert.equal((await teacher(db,'versions')).length,2);
  assert.equal((await teacher(db,'versions',{},'teacher-B')).length,0);
  await assert.rejects(teacher(db,'student',{code:'IT_X',pin:'different-fixture'},'teacher-B'),/resource_conflict/);
  await assert.rejects(teacher(db,'course',{document:{id:'IT_A',version:'v1'},manifest:{changed:true}}),/publication_conflict/);
  const {rows}=await db.query("select action,resource from vocab_teacher.audit where action in ('student','course')");
  assert.equal(rows.length,3);
  assert.ok(rows.every(row=>!JSON.stringify(row).includes('fixture-pin')));
});

test('private draft persists after database close and reopen',async()=>{
  const { mkdtemp, rm }=await import('node:fs/promises');
  const { tmpdir }=await import('node:os');
  const { join }=await import('node:path');
  const { PGlite }=await import(process.env.VOCAB_PGLITE_ENTRY||'@electric-sql/pglite');
  const { pgcrypto }=await import(process.env.VOCAB_PGLITE_CRYPTO||'@electric-sql/pglite/contrib/pgcrypto');
  const path=await mkdtemp(join(tmpdir(),'vocab-persist-'));
  const key={kind:'draft',name:'persistent'};
  const document={meta:{version:'v1'},rows:[{accepted:['合成備選']}]};
  let first,second;
  try {
    first=await fixture(path);
    await teacher(first,'save',{...key,document,expected:0});
    await first.close();
    first=null;
    second=new PGlite({dataDir:path,extensions:{pgcrypto}});
    assert.deepEqual(await teacher(second,'read',key),{revision:1,document});
  } finally {
    await first?.close();
    await second?.close();
    await rm(path,{recursive:true,force:true});
  }
});
