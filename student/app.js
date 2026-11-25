"use strict";
const $=x=>document.getElementById(x), h=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const preview=!!window.VOCAB_PREVIEW;
const APP_VERSION='0.3.11', PROTOCOL='supabase-v1';
let dailyDate='',dailySyncing=false,matchState=null,activeLock=null;
let clozeMethods={},clozeErrors={};
let sequence=0,authenticatedStudent='';
let courses=[],lesson=null,student='',pin='',phase=0,ix=0,flipped=false,round=0,attempt=0,answers={},testing=false,completed=false,uploading=false,language='en',sessionId='',sessionStarted=0,matchStarted=0,clozeStarted=0;
const eventPrefix='vocabSupabasePending:', rejectedPrefix='vocabSupabaseRejected:';
let backendConfig;
function getQueue(){return preview?[]:localItems(eventPrefix)}
function localItems(prefix){
 const keys=Object.keys(localStorage).filter(key=>key.startsWith(prefix));
 return keys.map(readLocal).filter(Boolean);
}
function enqueue(item){localStorage.setItem(eventPrefix+item.event.eventId,JSON.stringify(item))}
function removeEvents(ids){for(const id of ids)localStorage.removeItem(eventPrefix+id);pending()}
function pending(){
 const n=getQueue().length;
 $('pending').textContent='待確認事件：'+n+' 筆';
 $('sync').textContent='待確認 '+n+' 筆';
}
pending();
function uuid(){
 return crypto.randomUUID?.()||Array.from(crypto.getRandomValues(new Uint8Array(16)),n=>n.toString(16).padStart(2,'0')).join('');
}

// Daily session identity is enforced by PostgreSQL.
const snapshotKey='vocabSupabaseActive';
function snapshotPath({studentCode=student,courseId=lesson?.id,practiceDate=dailyDate,sessionId:sid=sessionId}={}){
 return [snapshotKey,backendConfig?.projectUrl,studentCode,courseId,practiceDate,sid].map(encodeURIComponent).join(':');
}
function readLocal(key){try{return JSON.parse(localStorage.getItem(key)||'null')}catch{return null}}
function reservationPath(code,id,date){return 'vocabSupabaseReservation:'+JSON.stringify([backendConfig?.projectUrl,code,id,date])}
function saveSnapshot(){if(preview||!activeLock||!sessionId||!dailyDate)return false;try{localStorage.setItem(snapshotPath(),JSON.stringify({student,courseId:lesson.id,courseVersion:lesson.version,lesson,practiceDate:dailyDate,sessionId,sessionStarted,matchStarted,clozeStarted,sequence,phase,ix,flipped,round,attempt,language,clozeOrder:clozeOrder.map(x=>x.id),matchState,clozeMethods,clozeErrors,clozeInput:phase===2?[...$('screen').querySelectorAll('[data-fill]')].map(x=>[x.dataset.fill,x.value]):[],completed}));return true;}catch(e){$('sync').textContent='本機進度儲存失敗，請確認瀏覽器未封鎖網站資料'}}
function restoreSnapshot(snap){
 if(!snap||snap.student!==student||snap.courseId!==lesson.id||snap.courseVersion!==lesson.version||snap.practiceDate!==dailyDate||snap.sessionId!==sessionId)return false;
 sequence=snap.sequence||0;
 sessionStarted=snap.sessionStarted||Date.now();matchStarted=snap.matchStarted||0;clozeStarted=snap.clozeStarted||0;phase=snap.phase||0;ix=snap.ix||0;flipped=!!snap.flipped;round=snap.round||0;attempt=snap.attempt||0;language=snap.language||language;
 clozeOrder=(snap.clozeOrder||[]).map(id=>lesson.words.find(x=>x.id===id)).filter(Boolean);
 clozeMethods=snap.clozeMethods||{};clozeErrors=snap.clozeErrors||{};matchState=snap.matchState||null;completed=!!snap.completed;
 $('workspace').classList.remove('hidden');$('courseTitle').textContent=lesson.title+'｜'+lesson.version;render();
 if(phase===2&&!completed){for(const [id,value] of (snap.clozeInput||[])){const input=$('screen').querySelector(`[data-fill="${id}"]`);if(input)input.value=value}saveSnapshot()}
 return true;
}
async function loadBackend(){
 if(backendConfig)return backendConfig;
 const response=await fetch('./backend.json',{cache:'no-store'});
 if(!response.ok)throw Error('尚未設定 Supabase 測試專案');
 const config=await response.json();
 let url;
 try{url=new URL(config.projectUrl)}catch{throw Error('Supabase 專案網址格式錯誤')}
 if(!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url.origin)||url.username||url.password||
    url.pathname!=='/'||url.search||url.hash||!/^sb_publishable_[A-Za-z0-9_-]+$/.test(config.publishableKey||''))
  throw Error('請填寫 Supabase Project URL 與 publishable key');
 backendConfig={projectUrl:url.origin,publishableKey:config.publishableKey};
 return backendConfig;
}

async function requestBackend(packet,timeout){
 const {projectUrl,publishableKey}=await loadBackend();
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),timeout);
 try{
  const response=await fetch(projectUrl+'/rest/v1/rpc/vocab_request',{
   method:'POST', headers:{apikey:publishableKey,'Content-Type':'application/json'},
   body:JSON.stringify({packet}),signal:controller.signal,redirect:'error'
  });
  if(!response.ok)throw Error('Supabase 請求未確認（HTTP '+response.status+'）');
  const data=await response.json();
  if(data.requestId!==packet.requestId||data.protocol!==PROTOCOL||data.appVersion!==APP_VERSION)
   throw Error('Supabase 協定不相容');
  return data;
 }finally{clearTimeout(timer)}
}

async function controlRequest(ctx,operation,extra={}){
 const data=await requestBackend({operation,requestId:uuid(),protocol:PROTOCOL,
  ...(operation==='version'?{}:{studentCode:ctx.student,pin:ctx.pin,courseId:ctx.lesson.id,courseVersion:ctx.lesson.version}),...extra},20000);
 if(!data.ok)throw Error(data.error||'Supabase 拒絕請求');
 return data;
}

function acquirePageLock(key){
 if(!navigator.locks)return Promise.reject(Error('此瀏覽器不支援練習分頁鎖，請使用支援 Web Locks 的瀏覽器'));
 return new Promise((resolve,reject)=>{
  navigator.locks.request(key,{ifAvailable:true},lock=>{
   if(!lock){resolve(null);return}
   return new Promise(release=>resolve({key,release}));
  }).catch(reject);
 });
}
async function dailyStart(nextLesson,nextStudent,nextPin,nextLanguage){
 if(dailySyncing)return;
 const ctx={lesson:nextLesson,student:nextStudent,pin:nextPin};
 let candidate=null;
 dailySyncing=true;$('start').disabled=true;$('workspace').inert=true;
 $('sync').textContent='正在由 Supabase 確認今日練習資格…';
 try{
  await controlRequest(ctx,'version');
  const status=await controlRequest(ctx,'daily_status');
  authenticatedStudent=nextStudent;
  const day=status.practiceDate;
  const key='vocab-page:'+JSON.stringify([backendConfig.projectUrl,nextStudent,nextLesson.id,day]);
  if(status.status==='completed'){
   if(activeLock?.key===key){
    localStorage.removeItem(snapshotPath());$('workspace').classList.add('hidden');
    activeLock.release();activeLock=null;
   }
   if(!activeLock){student=nextStudent;pin=nextPin}
   flush();
   $('sync').textContent='今天本課已達標完成，不能再次開始。';return;
  }
  candidate=activeLock?.key===key?activeLock:await acquirePageLock(key);
  if(!candidate)throw Error('這位學生的本課練習已在另一個分頁開啟');
  const reservation=reservationPath(nextStudent,nextLesson.id,day);
  let local=readLocal(reservation);
  // Recheck a known reservation under the page lock before changing it.
  let result=local?await controlRequest(ctx,'daily_status',{sessionId:local.sid}):status;
  if(result.practiceDate!==day)throw Error('臺灣日期已切換，請重新按開始');
  if(result.status==='not_started'||result.status==='reopened'){
   if(result.status==='reopened'||!local?.pending)local={sid:uuid(),pending:true};
   localStorage.setItem(reservation,JSON.stringify(local));
   result=await controlRequest(ctx,'daily_start',{sessionId:local.sid,practiceDate:day});
  }else if(result.status==='completed'){
   $('sync').textContent='今天本課已達標完成，不能再次開始。';return;
  }
  if(!local||result.status!=='in_progress'||result.practiceDate!==day||result.sessionId!==local.sid){
   throw Error('今天本課已有練習，請回原瀏覽器續作或由教師處理');
  }
  const ref={studentCode:nextStudent,courseId:nextLesson.id,practiceDate:day,sessionId:local.sid};
  let snap=readLocal(snapshotPath(ref));
  if(snap&&!(snap.student===nextStudent&&snap.courseId===nextLesson.id&&snap.practiceDate===day&&snap.sessionId===result.sessionId&&snap.courseVersion===result.courseVersion))snap=null;
  if(!snap&&!local.pending)throw Error('今天的練習缺少本機進度，請由教師處理');
  const content=result.courseVersion===nextLesson.version?nextLesson:snap?.lesson;
  if(!content||content.version!==result.courseVersion)throw Error('今日已使用 '+result.courseVersion+' 開始練習，請選擇原版本續作');
  saveSnapshot();
  if(activeLock&&activeLock!==candidate)activeLock.release();
  activeLock=candidate;lesson=content;student=nextStudent;pin=nextPin;dailyDate=day;sessionId=local.sid;
  language=nextLanguage;testing=false;
  if(snap){
   const isCompletion=item=>scopeOf(item.event)===scopeOf({...ref,courseVersion:result.courseVersion})&&item.event.action==='session_complete';
   if(getQueue().some(isCompletion))snap.completed=true;
   else if(snap.completed&&localItems(rejectedPrefix).some(isCompletion)){snap.completed=false;snap.round++}
  }
  if(snap&&restoreSnapshot(snap)){
   if(saveSnapshot())localStorage.setItem(reservation,JSON.stringify({sid:sessionId,pending:false}));
   $('sync').textContent='已恢復今天未完成的練習';flush();return;
  }
  sequence=0;sessionStarted=Date.now();matchStarted=0;clozeStarted=0;phase=0;clozeOrder=[];clozeMethods={};clozeErrors={};matchState=null;matchAttempt=0;ix=0;flipped=false;round=0;attempt=0;answers={};completed=false;
  $('workspace').classList.remove('hidden');$('courseTitle').textContent=lesson.title+'｜'+lesson.version;
  makeEvent('session_start',{wordCount:lesson.words.length});render();
  if(saveSnapshot())localStorage.setItem(reservation,JSON.stringify({sid:sessionId,pending:false}));
  flush();
 }catch(e){$('sync').textContent='無法開始：'+e.message}
 finally{
  if(candidate&&candidate!==activeLock)candidate.release();
  dailySyncing=false;$('start').disabled=false;$('workspace').inert=false;
 }
}

async function init(){if(preview){courses=[window.VOCAB_PREVIEW];$('course').innerHTML='<option value="0">'+h(courses[0].title)+'</option>';['student','pin','mode'].forEach(id=>$(id).parentElement.hidden=true);$('researchDetails').hidden=true;$('previewChoose').hidden=false;$('sync').textContent='教師預覽：不登入、不儲存、不上傳';return;}try{let index=await(await fetch('./lessons/index.json',{cache:'no-store'})).json();let loaded=[];for(const file of index.files.filter(f=>!(index.hidden||[]).includes(f))){let l=await(await fetch('./lessons/'+encodeURIComponent(file),{cache:'no-store'})).json();if(l.schema==='vocab-research-1')loaded.push(l)}courses=loaded;$('course').innerHTML=courses.map((x,i)=>`<option value="${i}">${h(x.title||x.id)}｜${h(x.version||'')}</option>`).join('');if(!courses.length)throw Error('課程清單沒有有效資料')}catch(e){$('sync').textContent='教材讀取失敗：'+e.message}}init();
function makeEvent(action,extra={}){if(preview||!activeLock||!lesson||!student)return;let e={eventId:uuid(),clientTime:new Date().toISOString(),study:'vocab',sequence:++sequence,sessionId,practiceDate:dailyDate,appVersion:APP_VERSION,elapsedSessionMs:Math.max(0,Date.now()-sessionStarted),courseId:lesson.id,courseVersion:lesson.version,studentCode:student,mode:testing?'delayed':'practice',meaningLanguage:language,stage:['card','match','cloze'][phase]||'system',action,round,attempt,...extra};enqueue({project:backendConfig.projectUrl,event:e,studentCode:student});pending();saveSnapshot();if(getQueue().length>=20)flush()}
// Durable local queue: batch up to 20 events. Never persist the student's PIN.
const BATCH_SIZE=20, MAX_PAYLOAD_CHARS=120000;
const scopeOf=e=>JSON.stringify([e.studentCode,e.courseId,e.courseVersion,e.practiceDate,e.sessionId]);
const retryLimits=new Map(), retryAfter=new Map();
const scopeKey=item=>JSON.stringify([item.project,scopeOf(item.event)]);
function defer(ref,message){
 retryAfter.set(ref.key,Date.now()+15000);
 $('sync').textContent=message;
 flush();
}
function flush(){
 if(preview||uploading||!backendConfig||!student||!pin)return;
 const queue=getQueue().filter(x=>x.project===backendConfig.projectUrl&&x.studentCode===student);
 // Storage key order is not an API guarantee. Preserve enqueue order within each session.
 queue.sort((a,b)=>(a.event.sequence??0)-(b.event.sequence??0));
 const first=queue.find(x=>(retryAfter.get(scopeKey(x))||0)<=Date.now());
 if(!first)return;
 const key=scopeKey(first);
 const batch=queue.filter(x=>scopeKey(x)===key).slice(0,retryLimits.get(key)||BATCH_SIZE);
 const ref={key,batch,requestId:uuid(),ids:batch.map(x=>x.event.eventId)};
 const packet={operation:'events',protocol:PROTOCOL,requestId:ref.requestId,events:batch.map(x=>x.event),studentCode:first.studentCode,pin};
 if(JSON.stringify(packet).length>MAX_PAYLOAD_CHARS){
  if(batch.length>1)retryLimits.set(key,Math.floor(batch.length/2));
  else{rejectBatch(ref,'payload_invalid');retryLimits.delete(key)}
  flush();return;
 }
 uploading=ref;
 requestBackend(packet,60000).then(data=>handleUpload(ref,data),()=>{
  if(uploading!==ref)return;
  uploading=false;defer(ref,'未收到後端確認，事件仍保留，稍後重送。');
 });
}
function rejectBatch(ref,error){
 for(const item of ref.batch)localStorage.setItem(rejectedPrefix+item.event.eventId,JSON.stringify({event:item.event,error}));
 removeEvents(ref.ids);
  $('sync').textContent=ref.batch.some(x=>x.event.action==='session_complete')
  ?'完成事件未獲 Supabase 確認，請重新按開始確認；原事件已保留。'
  :'有事件被 Supabase 拒收，已保留於本機備援下載。';
}
setInterval(flush,15000);
function handleUpload(ref,d){
 if(uploading!==ref)return;
 uploading=false;
 try{
  if(!d.ok){
   if(!d.permanent){defer(ref,'後端暫未確認：'+(d.error||'保留待送資料'));return}
   if(ref.ids.length>1)retryLimits.set(ref.key,Math.floor(ref.ids.length/2));
   else{rejectBatch(ref,d.error);retryLimits.delete(ref.key)}
   flush();return;
  }
  const acknowledged=new Set(d.eventIds||[]);
  if(!ref.ids.every(id=>acknowledged.has(id))){defer(ref,'後端未完整確認，保留待送資料。');return}
  removeEvents(ref.ids);
  retryLimits.delete(ref.key);retryAfter.delete(ref.key);
  const event=ref.batch[0].event;
  if(d.completedSessions?.includes(event.sessionId)){
   localStorage.removeItem(snapshotPath(event));
   if(scopeOf(event)===scopeOf({studentCode:student,courseId:lesson?.id,courseVersion:lesson?.version,practiceDate:dailyDate,sessionId}))
    $('sync').textContent='今日練習完成，Supabase 已確認並鎖定';
  }
  flush();
 }catch(e){$('sync').textContent='無法更新本機同步資料，請確認瀏覽器儲存空間。'}
}
$('retry').onclick=()=>{const code=$('student').value.trim(),secret=$('pin').value;if(!code||!secret){$('sync').textContent='請輸入原學生代碼與 PIN 再重送';return}if(activeLock&&code!==student){$('sync').textContent='請先完成目前練習';return}student=code;pin=secret;retryAfter.clear();flush()};$('downloadLog').onclick=()=>{
 const code=$('student').value.trim();
 if(!code||code!==authenticatedStudent){$('sync').textContent='請先透過 Supabase 確認原學生代碼，再下載備援事件。';return}
 const records=[...getQueue().map(x=>x.event),...localItems(rejectedPrefix).map(x=>({...x.event,syncError:x.error}))].filter(e=>e.studentCode===code);
 const blob=new Blob([JSON.stringify(records,null,2)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='pending-events.json';a.click();URL.revokeObjectURL(a.href);
};
$('start').onclick=()=>{const nextLesson=courses[+$('course').value],nextStudent=$('student').value.trim(),nextPin=$('pin').value,nextLanguage=$('language').value;
 if(!nextLesson)return alert('請選擇課程');if(!(nextLesson.availableLanguages||['en']).includes(nextLanguage))return alert('這一課尚未完成此語言的詞義');if(!preview&&(!nextStudent||!nextPin))return alert('請輸入學生代碼與 PIN');if(!nextLesson.words?.length)return alert('沒有可用生詞');

 if(preview){lesson=nextLesson;student=nextStudent||'PREVIEW';pin='';language=nextLanguage;sessionId=uuid();sessionStarted=Date.now();phase=Number($('previewStage').value);clozeOrder=[];clozeMethods={};clozeErrors={};matchState=null;round=phase===0?0:1;ix=0;flipped=false;completed=false;$('workspace').classList.remove('hidden');render();return;}
 dailyStart(nextLesson,nextStudent,nextPin,nextLanguage);
};
function msg(t,type='hint'){$('notice').innerHTML=`<p class="${type}">${h(t)}</p>`}
function progress(){$('stepLabel').textContent=testing?'延宕測驗':['① 字卡','② 詞義配對','③ 句子填空'][phase];$('progress').style.width=(testing?100:(phase*100/3+(phase===0?(ix+1)/lesson.words.length*100/3:0)))+'%';$('notice').innerHTML=''}
function render(){progress();if(completed){$('screen').innerHTML=preview?'<h2>預覽練習完成</h2><p>沒有任何研究資料被儲存或上傳。</p>':'<h2>本次練習已送出</h2><p>請確認資料上傳狀態；若尚有待確認事件，請使用重送功能。不要將此畫面視為後端已成功保存的證明。</p>';return}if(phase===0)card();else if(phase===1)match();else cloze()}
function card(){let x=lesson.words[ix];$('screen').innerHTML=`<h2>字卡 ${ix+1}／${lesson.words.length}</h2><div class="bigcard" id="flip"><strong>${h(x.word)}</strong><div class="face">${flipped?`${h(x.pinyin)}<br>${h((x.meanings||{})[language]||x.meaning)}`:'點此翻卡確認'}</div></div><div class="row" style="margin-top:15px"><button id="audio" class="secondary">🔊 發音</button><button id="next">${ix+1===lesson.words.length?'開始配對':'下一張'}</button></div>`;$('flip').onclick=()=>{flipped=!flipped;makeEvent('card_flip',{wordId:x.id,word:x.word,face:flipped?'back':'front'});saveSnapshot();card()};$('audio').onclick=()=>{if('speechSynthesis'in window){let u=new SpeechSynthesisUtterance(x.word);u.lang='zh-TW';speechSynthesis.speak(u)}makeEvent('card_audio',{wordId:x.id,word:x.word})};$('next').onclick=()=>{makeEvent('card_next',{wordId:x.id,word:x.word});flipped=false;if(++ix>=lesson.words.length){phase=1;ix=0;round=1;matchState=null;makeEvent('stage_start')}saveSnapshot();render()}}
function shuffled(a){let b=[...a];for(let i=b.length-1;i>0;i--){let j=Math.floor(Math.random()*(i+1));[b[i],b[j]]=[b[j],b[i]]}return b}
let matchAttempt=0;
function match(){
 const cached=matchState&&matchState.courseId===lesson.id?matchState:null;
 const group=cached?cached.left.map(id=>lesson.words.find(x=>x.id===id)).filter(Boolean):shuffled(lesson.words);
 const right=cached?cached.right.map(id=>lesson.words.find(x=>x.id===id)).filter(Boolean):shuffled(group);
 const done=new Set(cached?.done||[]), attempts=new Map(cached?.attempts||[]), errorsByWord=new Map(cached?.errorsByWord||[]);
 matchAttempt=[...attempts.values()].reduce((sum,count)=>sum+count,0);
 let chosen=null,errors=cached?.errors||0,chosenAt=0;
 function keepMatch(){matchState={courseId:lesson.id,left:group.map(x=>x.id),right:right.map(x=>x.id),done:[...done],attempts:[...attempts],errorsByWord:[...errorsByWord],errors};saveSnapshot()}
 if(!cached)keepMatch();
 if(!matchStarted)matchStarted=Date.now();round=1;
 const meaning=x=>(x.meanings||{})[language]||x.meaning;
 $('screen').innerHTML=`<h2>整課詞義卡片配對</h2><p class="hint">先選中文，再選對應詞義。配對正確後兩張卡片消失；配錯可繼續嘗試。</p><div class="matchsticky"><strong id="matchStatus">已完成 0／${group.length}</strong><span id="matchFeedback" role="status" aria-live="polite"></span><div class="bar"><div id="matchProgress" style="width:0%"></div></div></div><div class="matchgrid"><div><h3>中文生詞</h3><div class="matchpool">${group.map((x,i)=>`<button class="matchcard" data-left="${i}">${h(x.word)}</button>`).join('')}</div></div><div><h3>母語詞義</h3><div class="matchpool">${right.map((x,i)=>`<button class="matchcard" data-right="${i}">${h(meaning(x))}</button>`).join('')}</div></div></div><button id="nextGroup" disabled>完成全部配對後進入填空</button>`;
 const left=[...$('screen').querySelectorAll('[data-left]')],rb=[...$('screen').querySelectorAll('[data-right]')];
 group.forEach((x,i)=>{if(done.has(x.id))left[i].remove()});right.forEach((x,i)=>{if(done.has(x.id))rb[i].remove()});
 $('matchStatus').textContent=`已完成 ${done.size}／${group.length}｜錯誤 ${errors} 次`;
 $('matchProgress').style.width=100*done.size/group.length+'%';
 if(done.size===group.length){$('nextGroup').disabled=false;$('nextGroup').textContent='開始句子填空'}
 function clear(){[...left,...rb].forEach(b=>b.classList.remove('selected','wrong'))}
 function feedback(t,correct){$('matchFeedback').textContent=t;$('matchFeedback').className=correct===true?'ok':correct===false?'bad':'hint'}
 left.forEach((b,i)=>b.onclick=()=>{if(done.has(group[i].id))return;clear();chosen=i;chosenAt=Date.now();b.classList.add('selected');feedback('請選擇「'+group[i].word+'」的詞義')});
 rb.forEach((b,i)=>b.onclick=()=>{if(chosen===null||done.has(right[i].id))return;let x=group[chosen],y=right[i],correct=x.id===y.id;matchAttempt++;
  const n=(attempts.get(x.id)||0)+1;attempts.set(x.id,n);if(!correct)errorsByWord.set(x.id,(errorsByWord.get(x.id)||0)+1);
  makeEvent('answer',{wordId:x.id,word:x.word,selected:meaning(y),selectedWordId:y.id,correct,questionType:'meaning_match',attempt:matchAttempt,wordAttempt:n,firstAttempt:n===1,wordErrorCount:errorsByWord.get(x.id)||0,matchOrder:correct?done.size+1:null,remainingPairs:group.length-done.size,groupSize:group.length,elapsedMatchMs:Date.now()-matchStarted,selectionLatencyMs:Date.now()-chosenAt});
  clear();if(correct){done.add(x.id);left[chosen].remove();b.remove();feedback('配對正確！',true)}else{errors++;left[chosen].classList.add('wrong');b.classList.add('wrong');feedback('配對錯誤，請再試一次。',false)}chosen=null;keepMatch();
  $('matchStatus').textContent=`已完成 ${done.size}／${group.length}｜錯誤 ${errors} 次`;$('matchProgress').style.width=100*done.size/group.length+'%';
  if(done.size===group.length){makeEvent('round_end',{correctCount:done.size,total:group.length,errorCount:errors,elapsedMatchMs:Date.now()-matchStarted});$('nextGroup').disabled=false;$('nextGroup').textContent='開始句子填空';feedback('全課配對完成！',true);$('nextGroup').focus()}});
 $('nextGroup').onclick=()=>{if(done.size!==group.length)return;makeEvent('stage_pass',{passedStage:'match'});phase=2;round=1;attempt=0;saveSnapshot();render();makeEvent('stage_start')};
}
const norm=v=>String(v||'').normalize('NFKC').replace(/[\s，。！？,.!?]/g,'');
function classifyCloze(prompt,answer,allWords){const accepted=[prompt.word,...(prompt.accepted||[])];const correct=accepted.some(v=>norm(v)===norm(answer));const actual=correct?allWords.find(w=>norm(w.word)===norm(answer)):null;return {correct,actualWordId:actual?actual.id:null,actualWord:actual?actual.word:null};}
let clozeOrder=[];
function cloze(){if(!clozeStarted)clozeStarted=Date.now();if(!clozeOrder.length)clozeOrder=shuffled(lesson.words);saveSnapshot();$('screen').innerHTML=`<h2>${testing?'延宕測驗':'無選項句子填空'}｜第 ${round||1} 輪</h2><p class="hint">直接打字或使用裝置鍵盤語音輸入。可按麥克風執行瀏覽器語音辨識（若支援）。</p>`+clozeOrder.map(x=>`<div class="item"><label>${h(x.sentence)}</label><div class="row"><div class="grow"><input data-fill="${h(x.id)}" autocomplete="off" placeholder="輸入生詞"></div><button class="secondary" data-mic="${h(x.id)}">🎤 語音</button></div><div class="small" data-inputmethod="${h(x.id)}">目前：打字／鍵盤輸入</div></div>`).join('')+`<button id="submitCloze">${testing?'送出正式測驗':'送出本輪填空'}</button>`;
 const methods=clozeMethods;$('screen').querySelectorAll('[data-mic]').forEach(btn=>btn.onclick=()=>{let id=btn.dataset.mic,R=window.SpeechRecognition||window.webkitSpeechRecognition;if(!R){msg('本瀏覽器不支援語音辨識，請改用打字。','bad');return}const screen=$('screen').querySelector('[data-fill="'+id+'"]');let rec=new R();rec.lang='zh-TW';rec.interimResults=false;rec.maxAlternatives=1;rec.onresult=e=>{if(!screen?.isConnected||dailySyncing)return;let t=e.results[0][0].transcript;$('screen').querySelector(`[data-fill="${id}"]`).value=t;methods[id]='speech';$('screen').querySelector(`[data-inputmethod="${id}"]`).textContent='語音辨識完成，請核對或修正文字';makeEvent('speech_transcript',{wordId:id,transcript:t});saveSnapshot()};rec.onerror=e=>{if(screen?.isConnected&&!dailySyncing)makeEvent('speech_error',{wordId:id,error:e.error})};rec.start()});
 $('screen').querySelectorAll('[data-fill]').forEach(inp=>inp.addEventListener('input',()=>{if(methods[inp.dataset.fill]==='speech')methods[inp.dataset.fill]='speech_edited';saveSnapshot()}));
 const submit=$('submitCloze');
 submit.onclick=async()=>{
  const entries=clozeOrder.map(word=>({word,value:$('screen').querySelector(`[data-fill="${word.id}"]`).value,
   inputMethod:methods[word.id]||'typed'}));
  if(entries.some(x=>!norm(x.value)))return msg('請填寫所有空格','bad');
  const scope=sessionId, submissionId=uuid();
  let grades=null;
  if(!preview&&lesson.clozeGrading==='server'){
   submit.disabled=true;
   try{
    const result=await controlRequest({lesson,student,pin},'grade_cloze',{sessionId,
     answers:Object.fromEntries(entries.map(x=>[x.word.id,x.value]))});
    grades=result.grades;
    if(!grades||entries.some(x=>typeof grades[x.word.id]!=='boolean'))throw Error('缺少完整判分');
   }catch(e){
    if(submit.isConnected)msg('判分未完成，答案仍保留。請確認網路後重送。','bad');
    return;
   }finally{submit.disabled=false}
   if(!submit.isConnected||sessionId!==scope||dailySyncing)return;
  }
  const scores=[];
  for(const {word,value,inputMethod} of entries){
   const correct=grades?grades[word.id]:classifyCloze(word,value,lesson.words).correct;
   const isTargetWord=norm(word.word)===norm(value);
   const actual=correct?lesson.words.find(w=>norm(w.word)===norm(value)):null;
   scores.push(correct);
   if(!correct)clozeErrors[word.id]=(clozeErrors[word.id]||0)+1;
   makeEvent('answer',{wordId:word.id,word:word.word,selected:value,correct,
    actualWordId:actual?.id??null,actualWord:actual?.word??null,isTargetWord,questionType:'context_cloze',submissionId,
    attempt:round||1,wordAttempt:round||1,firstAttempt:(round||1)===1,
    wordErrorCount:clozeErrors[word.id]||0,elapsedClozeRoundMs:Date.now()-clozeStarted,inputMethod});
  }
  const count=scores.filter(Boolean).length;
  makeEvent('round_end',{submissionId,correctCount:count,total:scores.length});
  if(count===scores.length){
   makeEvent('stage_pass',{passedStage:'cloze',submissionId});makeEvent('session_complete',{submissionId});
   completed=true;saveSnapshot();render();flush();
  }else{
   msg(`本輪 ${count}/${scores.length}，尚未全對，請繼續練習。`,'bad');
   round++;saveSnapshot();
   submit.textContent='重新填空';submit.onclick=()=>{clozeStarted=Date.now();clozeMethods={};cloze()};
  }
 };
}
