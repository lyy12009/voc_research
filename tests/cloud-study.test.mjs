import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdtempSync, rmSync, rmdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join } from 'node:path';
import test from 'node:test';
import { generate, scope } from './synthetic-study.mjs';

const ref = process.env.VOCAB_STAGE_REF;
const cli = process.env.VOCAB_SUPABASE_CLI || 'supabase';
const production = 'pznehaenpfadyjdqgpyh';

function supabase(args) {
  const call = spawnSync(cli, args, {encoding:'utf8',maxBuffer:30_000_000,windowsHide:true});
  assert.equal(call.status, 0, 'Supabase CLI command failed: '+args.slice(0,2).join(' '));
  return JSON.parse(call.stdout);
}

const encoded = data => "convert_from(decode('"+Buffer.from(JSON.stringify(data)).toString('base64')+"','base64'),'UTF8')::jsonb";
const tableColumns = {
  daily:'student_code,course_id,course_version,practice_date,session_id,started_at,completed_at',
  events:'event_id,session_id,received_at,correct_server,payload',
  delayed_tests:'student_code,course_id,course_version,end_date,makeup_date,submitted_at,test_date',
  delayed_answers:'student_code,course_id,word_id,target_word,category,actual_answer,answer_type,target_hit,correct_server',
};

test('managed Supabase synthetic research reconciles the actual Streamlit dashboard and workbook', {timeout:300000}, t=>{
  assert.match(ref || '', /^[a-z0-9]{20}$/);
  assert.notEqual(ref,production);
  const {projects} = supabase(['projects','list','--output-format','json']);
  assert.equal(projects.find(project=>project.ref===ref)?.name,'VocabResearch Integration');
  const work = mkdtempSync(join(tmpdir(),'vocab-stage-'));
  const file = join(work,'query.sql');
  t.after(()=>{ rmSync(file,{force:true}); rmdirSync(work); });
  function run(sql, write=false) {
    writeFileSync(file,write?sql:'set transaction read only;\n'+sql,'utf8');
    return supabase(['db','query','--remote='+ref,'--file',file,'--output','json','--yes']).rows;
  }
  const corpus=generate();
  const students=corpus.students.slice(0,10);
  const course=corpus.courses[0];
  const keep = row=>row.course_id===course.id && students.includes(row.student_code);
  const sessions=corpus.sessions.filter(keep);
  const validSessions=new Set(sessions.map(row=>row.session_id));
  const events=corpus.events.filter(row=>validSessions.has(row.session_id));
  const delayedTests=corpus.tests.filter(keep), delayedAnswers=corpus.answers.filter(keep);
  const identity="'https://issuer.test','teacher-A'";
  const request=(op, json)=>"vocab_teacher.request("+identity+",'"+op+"',"+encoded(json)+");";
  if(process.env.VOCAB_STAGE_REUSE!=="1"){
    const principals=students.map(code=>"select "+request('student',{code,pin:randomUUID()}))
      .join('\n');
    // Preserve any existing scenario fixture on retries.
    const register=principals.split('\n').map(statement=>
      "do $$ begin "+statement.replace(/^select /,'perform ')+" exception when others then "+
      "if SQLERRM <> 'resource_conflict' then raise; end if; end $$;").join('\n');
    run("insert into vocab_teacher.identities values ('https://issuer.test','teacher-A',true) on conflict do nothing;"+
        register+['v1','v2'].map(version=>"select "+request('course',{document:{...course,version},manifest:{synthetic:true}})).join('\n'),true);
    for(const [table,rows] of Object.entries({daily:sessions,events,delayed_tests:delayedTests,delayed_answers:delayedAnswers})) {
      const cols=tableColumns[table];
      for(let start=0;start<rows.length;start+=500)
        run("insert into vocab_private."+table+" ("+cols+") select "+cols+
            " from jsonb_populate_recordset(null::vocab_private."+table+","+encoded(rows.slice(start,start+500))+") on conflict do nothing",true);
    }
  }
  const query={...scope,course:course.id};
  const [{metadata,delayed}]=run("select vocab_teacher.study_metadata("+identity+","+encoded(query)+") metadata,"+
      "vocab_teacher.delayed("+identity+","+encoded({operation:'read',course:course.id})+") delayed");
  metadata.students=metadata.students.filter(student=>students.includes(student));
  assert.equal(metadata.students.length,students.length);
  const parts={},history={};
  for(const student of students){
    const [row]=run("select vocab_teacher.research("+identity+","+encoded({...query,student})+") part,"+
      "vocab_teacher.delayed("+identity+","+encoded({operation:'history',student})+") history");
    parts[student]=row.part;
    history[student]=row.history;
  }
  const [{stored}]=run(`with d as (select * from vocab_private.daily where course_id='SYN_L1'),
      a as (select * from vocab_private.delayed_answers where course_id='SYN_L1'),
      t as (select * from vocab_private.delayed_tests where course_id='SYN_L1')
      select jsonb_build_object('events',(select count(*) from vocab_private.events join d using(session_id)),
        'sessions',(select count(*) from d),'interrupted',(select count(*) from d where completed_at is null),
        'missed',(select count(*) from t where test_date is null),'makeup',(select count(*) from t where is_makeup),
        'target',(select count(*) from a where target_hit),'acceptable',(select count(*) from a where correct_server),
        'items',(select count(*) from a)) stored`);
  // The AppTest uses its standard empty course widget; the SQL data and cohort here are already restricted.
  assert.equal(Number(stored.events),events.length);
  assert.equal(Number(stored.sessions),sessions.length);
  const result=spawnSync(process.env.VOCAB_PYTHON||'python',['tests/study_acceptance.py'],{
    input:JSON.stringify({scope:{...scope,course:''},metadata,parts,history,delayed,stored}),encoding:'utf8',
    maxBuffer:10_000_000,env:{...process.env,PYTHONPATH:[process.cwd(),process.env.PYTHONPATH].filter(Boolean).join(delimiter)},
  });
  assert.equal(result.status,0,result.stderr||result.stdout);
  t.diagnostic(result.stdout.trim());
});
