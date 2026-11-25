import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { fixture, teacher } from './fixture.mjs';

export const seedValue = 20261125;
const counts = [37,26,36,32,30];
const labels = ['textbook','topic','supplement'];
const posLabels = ['名詞','動詞','形容詞',null];
export const scope = {from:'2026-09-01',to:'2026-10-10',student:'',course:'',word:'',category:''};
const at = (day, hour=12) => new Date(Date.parse(scope.from+'T00:00:00+08:00')+day*86400000+hour*3600000).toISOString();
const dayAt = day => at(day,12).slice(0,10);
const eventId = (sid,suffix) => createHash('sha256').update(sid+':'+suffix).digest('hex');

export function generate(seed = seedValue) {
  let state=seed>>>0;
  const random=()=>{state=(Math.imul(1664525,state)+1013904223)>>>0;return state/4294967296;};
  const students=Array.from({length:20},(_,i)=>'SYN_'+String(i+1).padStart(2,'0'));
  const courses=counts.map((count,i)=>({
    id:'SYN_L'+(i+1),words:Array.from({length:count},(_,n)=>({
      id:'W_SYN_'+i+'_'+n,word:'模擬詞'+i+'號'+n,accepted:['模擬備選'+i+'號'+n],
      meanings:{en:'synthetic '+i+':'+n},category:labels[n%3],part_of_speech:posLabels[n%4],
    })),
  }));
  const sessions=[],events=[],tests=[],answers=[];
  for(const [j,student] of students.entries()) {
    for(const [i,course] of courses.entries()) {
      const id=course.id, base=i*5, ended=base+3, behavior=(j+i)%10;
      const appointment=behavior===6?null:behavior===7?ended+17:ended+8+(j%7);
      const days=[base,base+2,...(behavior%2===0?[ended+5]:[])];
      for(const [index,day] of days.entries()) {
        const version=index===0?'v1':'v2';
        const sid=eventId(student,id+':'+day);
        const interrupted=behavior===5&&index===0;
        const session={student_code:student,course_id:id,course_version:version,practice_date:dayAt(day),
          session_id:sid,started_at:at(day,9),completed_at:interrupted?null:at(day,11)};
        sessions.push(session);
        let sequence=0;
        const push=(action, stage, word, extras={}, score=null)=>{
          sequence++;
          const payload={eventId:eventId(sid,sequence),study:'vocab',mode:'practice',studentCode:student,
            courseId:id,courseVersion:version,practiceDate:session.practice_date,sessionId:sid,
            action,stage,sequence,elapsedSessionMs:sequence*650,clientTime:at(day,10),...extras};
          if(word) Object.assign(payload,{wordId:word.id,word:word.word});
          events.push({event_id:payload.eventId,session_id:sid,received_at:at(day,10),
            correct_server:score,payload});
        };
        push('session_start','card');
        for(const word of course.words)push('card_flip','card',word);
        if(interrupted)continue;
        for(const word of course.words)push('answer','match',word,{
          questionType:'meaning_match',wordAttempt:1,firstAttempt:true,selected:word.meanings.en,
        },true);
        const passes=index===0&&[1,2,3].includes(behavior)?3:1;
        for(let round=1;round<=passes;round++) {
          const submissionId=eventId(sid,'round'+round);
          for(const [n,word] of course.words.entries()) {
            const wrong=round<passes&&(n===0||random()<0.13);
            const alternate=n===0&&[4,9].includes(behavior);
            const selected=wrong?'模擬錯答':alternate?word.accepted[0]:word.word;
            push('answer','cloze',word,{questionType:'context_cloze',wordAttempt:round,attempt:round,
              round,firstAttempt:round===1,submissionId,selected},!wrong);
          }
          push('round_end','cloze',null,{round,submissionId});
        }
        push('session_complete','cloze',null,{round:passes,submissionId:eventId(sid,'round'+passes)});
      }
      tests.push({student_code:student,course_id:id,course_version:'v1',end_date:dayAt(ended),
        makeup_date:behavior===7?dayAt(appointment):null,submitted_at:appointment===null?null:at(appointment,13),
        test_date:appointment===null?null:dayAt(appointment)});
      if(appointment===null)continue;
      for(const [n,word] of course.words.entries()) {
        const alternate=n===0&&[4,9].includes(behavior);
        const wrong=!alternate&&((behavior===2&&n===0)||random()<0.18);
        answers.push({student_code:student,course_id:id,word_id:word.id,target_word:word.word,
          category:word.category,actual_answer:wrong?'模擬錯答':alternate?word.accepted[0]:word.word,
          answer_type:wrong?'incorrect':alternate?'accepted_alternative':'target',
          target_hit:!alternate&&!wrong,correct_server:!wrong});
      }
    }
  }
  return {students,courses,sessions,events,tests,answers};
}

const columns = {
  daily:'student_code,course_id,course_version,practice_date,session_id,started_at,completed_at',
  events:'event_id,session_id,received_at,correct_server,payload',
  delayed_tests:'student_code,course_id,course_version,end_date,makeup_date,submitted_at,test_date',
  delayed_answers:'student_code,course_id,word_id,target_word,category,actual_answer,answer_type,target_hit,correct_server',
};
async function insert(db, table, records){
  const cols=columns[table];
  for(let i=0;i<records.length;i+=1000)
    await db.query('insert into vocab_private.'+table+' ('+cols+') select '+cols+
      ' from jsonb_populate_recordset(null::vocab_private.'+table+',$1) on conflict do nothing',[records.slice(i,i+1000)]);
}

export async function openSynthetic() {
  const data=generate(),db=await fixture();
  try{
    for(const student of data.students)await teacher(db,'student',{code:student,pin:'synthetic-fixture-only'});
    for(const course of data.courses)for(const version of ['v1','v2'])
      await teacher(db,'course',{document:{...course,version},manifest:{synthetic:true}});
    await insert(db,'daily',data.sessions);
    await insert(db,'events',data.events);
    await insert(db,'events',data.events.slice(0,200));
    await insert(db,'delayed_tests',data.tests);
    await insert(db,'delayed_answers',data.answers);
    return {db,data};
  }catch(error){await db.close();throw error;}
}

export async function readStudy(db, functionName, packet, subject='teacher-A') {
  const functions={research:'vocab_teacher.research',delayed:'vocab_teacher.delayed',metadata:'vocab_teacher.study_metadata'};
  const result=await db.query('select '+functions[functionName]+'($1,$2,$3) result',['https://issuer.test',subject,packet]);
  return result.rows[0].result;
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  const {db,data}=await openSynthetic();
  try{
    const {rows}=await db.query('select count(*)::int n from vocab_private.events');
    console.log(JSON.stringify({synthetic:true,seed:seedValue,students:data.students.length,
      courses:data.courses.length,word_counts:counts,sessions:data.sessions.length,events:rows[0].n,
      scheduled:data.tests.length,answers:data.answers.length}));
  }finally{await db.close();}
}
