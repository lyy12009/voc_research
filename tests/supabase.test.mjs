import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { after, before, test } from 'node:test';
import vm from 'node:vm';

const { PGlite } = await import(process.env.VOCAB_PGLITE_ENTRY || '@electric-sql/pglite');
const { pgcrypto } = await import(process.env.VOCAB_PGLITE_CRYPTO || '@electric-sql/pglite/contrib/pgcrypto');
const sql = await readFile(new URL('../supabase/migrations/202611250001_vocab.sql',import.meta.url),'utf8');
const studentJs = await readFile(new URL('../student/app.js',import.meta.url),'utf8');
const db = new PGlite({extensions:{pgcrypto}});
const name = 'S001';
const pin = 'fixture-only-1';
let day;
const words = [
  {id:'W1',word:'甲',meanings:{en:'alpha',vi:'a',id:'alfa'},accepted:['第一']},
  {id:'W2',word:'乙',meanings:{en:'beta',vi:'b',id:'beta'},accepted:['第二']},
];

before(async()=>{
  await db.exec('create role anon; create role authenticated;');
  await db.exec(sql);
  await db.exec(await readFile(new URL('../supabase/migrations/202611250002_private_cloze.sql',import.meta.url),'utf8'));
  await db.query('select vocab_private.register_student($1,$2)',[name,pin]);
  await db.query('select vocab_private.register_student($1,$2)',['S002','fixture-only-2']);
  for(const [id,version] of [['L1','v1'],['L1','v2'],['L2','v1'],['L3','v1']]){
    await db.query('select vocab_private.register_course($1)',[{id,version,words}]);
  }
  day=(await request('daily_status')).practiceDate;
});
after(()=>db.close());

async function rpc(packet){
  const result=await db.query('select public.vocab_request($1) result',[packet]);
  return result.rows[0].result;
}
const request=(operation,extra={})=>rpc({
  operation,protocol:'supabase-v1',requestId:randomUUID(),studentCode:name,pin,
  courseId:'L1',courseVersion:'v1',practiceDate:day,...extra,
});
const ids={};
const start=async(courseId='L1')=>{
  const sessionId=randomUUID();
  const result=await request('daily_start',{courseId,sessionId});
  assert.equal(result.sessionId,sessionId);
  ids[courseId]=sessionId;
  return result;
};
const event=(courseId='L1',extra={})=>({
  eventId:randomUUID(),sessionId:ids[courseId],practiceDate:day,studentCode:name,courseId,courseVersion:'v1',
  study:'vocab',mode:'practice',stage:'card',action:'session_start',round:1,...extra,
});
const send=events=>request('events',{events});
const count=async(table)=>Number((await db.query('select count(*) as n from vocab_private.'+table)).rows[0].n);

test('Supabase migration creates restricted API and reports its protocol',async()=>{
  assert.equal((await request('version')).protocol,'supabase-v1');
  const grants=await db.query(`select has_schema_privilege('anon','vocab_private','usage') direct_access,
    has_function_privilege('anon','public.vocab_request(jsonb)','execute') rpc,
    has_function_privilege('anon','vocab_private.register_student(text,text)','execute') admin`);
  assert.deepEqual(grants.rows[0],{direct_access:false,rpc:true,admin:false});
  await db.exec('set role anon');
  try{
    assert.equal((await request('daily_status')).status,'not_started');
    await assert.rejects(db.query('select * from vocab_private.research_events'),/permission denied/);
  }finally{await db.exec('reset role')}
});

test('GAS-shaped course registration preserves IDs and two versions share the daily slot',async()=>{
  assert.equal((await start()).created,true);
  const denied=await request('daily_start',{courseVersion:'v2',sessionId:randomUUID()});
  assert.equal(denied.created,false);
  assert.equal(denied.courseVersion,'v1');
  assert.equal(denied.sessionId,'');
  assert.equal((await request('daily_status',{sessionId:ids.L1})).sessionId,ids.L1);
  assert.equal(await count('daily'),1);
});

test('only the active session can receive alias grades and no answer key is returned',async()=>{
  const wrong=await request('grade_cloze',{sessionId:ids.L1,answers:{W1:'錯誤',W2:'第二'}});
  assert.deepEqual(wrong.grades,{W1:false,W2:true});
  const right=await request('grade_cloze',{sessionId:ids.L1,answers:{W1:'第一。',W2:'乙'}});
  assert.deepEqual(right.grades,{W1:true,W2:true});
  const canonical=await request('grade_cloze',{sessionId:ids.L1,answers:{W1:'甲',W2:'乙'}});
  assert.deepEqual(canonical.grades,right.grades);
  assert.equal(JSON.stringify(right).includes('第一'),false);
  assert.equal((await request('grade_cloze',{sessionId:ids.L1,answers:{W1:'第一'}})).error,'invalid_answers');
  assert.equal((await request('grade_cloze',{studentCode:'S002',pin:'fixture-only-2',sessionId:ids.L1,
    answers:{W1:'第一',W2:'第二'}})).error,'daily_session_mismatch');
  assert.equal(await count('events'),0);
});

test('invalid batches are atomic; intact retry deduplicates and mixed sessions are rejected',async()=>{
  await start('L2');
  const valid=event();
  assert.equal((await send([valid,event('L2')])).error,'mixed_batch_scope');
  assert.equal(await count('events'),0);
  assert.equal((await send([valid,event('L1',{action:'bad'})])).error,'invalid_event');
  assert.equal(await count('events'),0);
  assert.equal((await send([valid])).ok,true);
  assert.equal((await send([valid])).ok,true);
  assert.equal(await count('events'),1);
  assert.equal((await send([{...valid,action:'card_flip'}])).error,'event_id_conflict');
});

test('can only complete using one full submission; retries and account isolation hold',async()=>{
  const make=extra=>event('L1',extra);
  const match=words.map(w=>make({action:'answer',stage:'match',questionType:'meaning_match',wordId:w.id,
    selectedWordId:w.id,selected:w.meanings.vi,meaningLanguage:'vi'}));
  assert.equal((await send([...match,make({action:'stage_pass',stage:'match'})])).ok,true);
  const attempt=randomUUID();
  const cloze=(w,submissionId)=>make({action:'answer',stage:'cloze',questionType:'context_cloze',wordId:w.id,
    selected:' '+w.accepted[0]+'。',submissionId});
  assert.equal((await send([cloze(words[0],attempt),cloze(words[1],randomUUID())])).ok,true);
  const pass=make({action:'stage_pass',stage:'cloze',submissionId:attempt});
  const done=make({action:'session_complete',stage:'cloze',submissionId:attempt});
  assert.equal((await send([pass,done])).error,'daily_completion_not_verified');
  assert.equal((await request('daily_status')).status,'in_progress');
  assert.deepEqual((await send([cloze(words[1],attempt),pass,done])).completedSessions,[ids.L1]);
  const priorCount=await count('events');
  assert.deepEqual((await send([done])).completedSessions,[ids.L1]);
  assert.equal(await count('events'),priorCount);
  const views=await db.query(`select (select count(*)::int from vocab_private.research_sessions) sessions,
    (select count(*)::int from vocab_private.research_events where correct_server) correct`);
  assert.deepEqual(views.rows[0],{sessions:2,correct:5});
  assert.equal((await request('daily_start',{sessionId:randomUUID(),courseVersion:'v2'})).status,'completed');
  const other={studentCode:'S002',pin:'fixture-only-2'};
  assert.equal((await request('daily_status',other)).status,'not_started');
  assert.equal((await request('events',{...other,events:[done]})).error,'daily_session_mismatch');
});

test('locks repeated invalid PIN attempts without exposing student rows',async()=>{
  const other={studentCode:'S002',pin:'invalid-test-pin'};
  for(let i=0;i<12;i++)assert.equal((await request('daily_status',other)).error,'auth_failed');
  assert.equal((await request('daily_status',other)).error,'temporary_auth_lock');
  assert.equal((await request('daily_status')).status,'completed');
});

test('student JavaScript uses Supabase RPC and stores no PIN in its persistent queue',async()=>{
  const entries=Object.create(null);
  const localStorage=new Proxy(entries,{get(target,key){
    return {
      getItem:k=>target[k]??null,
      setItem:(k,v)=>{target[k]=String(v)},
      removeItem:k=>{delete target[k]},
    }[key]??target[key];
  }});
  const nodes=new Map();
  const getElementById=id=>{
    if(!nodes.has(id))nodes.set(id,{classList:{remove(){},add(){}},style:{},
      querySelectorAll:()=>[],querySelector:()=>null});
    return nodes.get(id);
  };
  const calls=[];
  const outstanding=[];
  const ctx=vm.createContext({
    document:{getElementById},window:{},URL,AbortController,localStorage,setInterval(){},setTimeout,clearTimeout,
    crypto:{randomUUID},navigator:{locks:{async request(_key,_options,callback){return callback({})}}},
    async fetch(url,options){
      if(url==='./backend.json')return {ok:true,json:async()=>({projectUrl:'https://fixture.supabase.co',publishableKey:'sb_publishable_fixture'})};
      if(url==='./lessons/index.json')return {ok:true,json:async()=>({files:[]})};
      assert.equal(url,'https://fixture.supabase.co/rest/v1/rpc/vocab_request');
      assert.equal(options.headers.apikey,'sb_publishable_fixture');
      const {packet}=JSON.parse(options.body);
      calls.push(packet);
      const result=rpc(packet);
      outstanding.push(result);
      return {ok:true,json:()=>result};
    },
  });
  vm.runInContext(studentJs,ctx);
  await ctx.dailyStart({id:'L3',version:'v1',title:'測試',words},name,pin,'en');
  await Promise.all(outstanding);
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls.map(call=>call.operation),['version','daily_status','daily_start','events']);
  assert.equal(calls[0].pin,undefined);
  assert.equal(vm.runInContext('getQueue().length',ctx),0);
  assert.equal(JSON.stringify(entries).includes(pin),false);
  assert.equal((await request('daily_status',{courseId:'L3'})).status,'in_progress');
});
