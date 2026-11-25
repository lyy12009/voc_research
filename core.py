"""Pure helpers for the teacher GUI. No network side effects."""
import json,re,hashlib,io,zipfile,unicodedata
from pathlib import Path

TEXT_PARTS=('對話1','對話2','文章1','文章2')
SCHEMA='vocab-research-1'
APP_VERSION='0.3.11'
BACKEND_PROTOCOL='supabase-v1'

def load_book(path):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(data,list): raise ValueError('教材 JSON 應為課次物件陣列')
    for i,item in enumerate(data):
        if not isinstance(item,dict) or '冊' not in item or '課' not in item: raise ValueError(f'第 {i+1} 筆缺少「冊」或「課」')
    return data

def lesson_key(lesson): return str(lesson['冊'])+'｜'+str(lesson['課'])

def unique_words(lesson,selected_parts):
    found=[]; sources={}
    for part in selected_parts:
        for word in lesson.get(part+'生詞',[]) or []:
            word=str(word).strip()
            if not word:continue
            if word not in sources:
                found.append(word); sources[word]=[]
            sources[word].append(part)
    return [{'word':w,'pinyin':'','meaning':'','meanings':{'en':'','vi':'','id':''},'sentence':'','accepted':'','category':'textbook','sources':'、'.join(sources[w])} for w in found]

def sentence_candidates(lesson,word,parts=None):
    """Only extract, do not invent sentences. Prefer a complete speaker utterance or punctuation-delimited clause."""
    if not word:return []
    result=[]
    for part in (parts or TEXT_PARTS):
        text=lesson.get(part,'') or ''
        for line in text.splitlines():
            if word not in line: continue
            content=line.split('：',1)[-1].strip()
            for chunk in re.split(r'(?<=[。！？!?])',content):
                chunk=chunk.strip()
                if word not in chunk:continue
                # Require exactly one occurrence; avoids multi-blank/ambiguity.
                if chunk.count(word)!=1: continue
                masked=chunk.replace(word,'＿＿',1)
                if masked not in result:result.append(masked)
    return result[:25]

def normalize_blank(sentence):
    # A contiguous run of >=2 full-/half-width underscores is one blank.
    return re.sub(r'[_＿]{2,}', '＿＿', str(sentence or '').strip())

def valid_blank(sentence):
    s=normalize_blank(sentence)
    return s.count('＿＿')==1 and '_' not in s.replace('＿＿','') and '＿' not in s.replace('＿＿','')

def stable_word_id(word):
    return 'W'+hashlib.sha256(word.encode('utf-8')).hexdigest()[:10].upper()

def accepted_answers(value):
    # Drafts store a string, while imported rows may already contain a list.
    if isinstance(value, str):
        value = re.split(r'[,，;；、\n]', value)
    if not isinstance(value, list):
        return []
    return [answer.strip() for answer in value if isinstance(answer, str) and answer.strip()]


def validate_and_build(book,lesson,rows,meta,preview=False):
    problems=[]; selected=[r for r in rows if r.get("included",True)]
    if not selected:problems.append('請至少勾選一個納入練習的生詞')
    id_=str(meta.get('id','')).strip(); version=str(meta.get('version','')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,90}',id_): problems.append('課程 ID 只能是英文、數字、底線、連字號或句點（長度 1–90）')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,90}',version):problems.append('版本格式錯誤')
    words=[]; seen=set(); meanings_by_lang={lang:{} for lang in ('en','vi','id')}
    for row in selected:
        w=str(row.get('word') or '').strip(); meaning=str(row.get('meaning') or '').strip(); sentence=normalize_blank(row.get('sentence'))
        if not w:problems.append('出現空白生詞');continue
        if w in seen:problems.append(f'重複生詞：{w}')
        seen.add(w)
        ml=row.get('meanings') or {}
        if not isinstance(ml,dict): ml={}
        ml={lang:str(ml.get(lang) or '').strip() for lang in ('en','vi','id')}
        # 舊版 meaning 不明確對應哪一種母語，不擅自認定為英文，僅保留待教師指定。
        if not any(ml.values()):problems.append(f'「{w}」缺少三語詞義（至少需填一種語言）')
        for lang,val in ml.items():
            norm_val=re.sub(r"[\s，。！？,.!?]", "", unicodedata.normalize("NFKC",val))
            if val and norm_val in meanings_by_lang[lang]:
                problems.append(f'「{w}」與「{meanings_by_lang[lang][norm_val]}」的 {lang} 詞義選項重複')
            elif val: meanings_by_lang[lang][norm_val]=w
        if not valid_blank(sentence):problems.append(f'「{w}」填空句必須包含且僅包含一個「＿＿」')
        if w in sentence:problems.append(f'「{w}」填空句仍包含目標生詞，可能洩漏答案')
        aliases=accepted_answers(row.get('accepted'))
        words.append({'id':stable_word_id(w),'word':w,'pinyin':str(row.get('pinyin') or '').strip(),'meaning':meaning,'meanings':ml,'sentence':sentence,'category':str(row.get('category') or 'textbook'),'accepted':aliases,'source':str(row.get('sources') or '')})
    # 逐種語言檢查整組配對的完整性；只有全課均有詞義的語言才供學生選擇。
    available_langs=[lang for lang in ('en','vi','id') if all(w['meanings'][lang] for w in words)]
    if words and not available_langs: problems.append('至少需有一種語言完成全課所有生詞的詞義，才能發布配對練習')
    if len({w['id'] for w in words})!=len(words):problems.append('詞彙 ID 衝突')
    if not meta.get('title'):problems.append('課程名稱不可空白')
    if problems and not preview:return problems,None,None
    public={'schema':SCHEMA,'id':id_,'version':version,'title':str(meta['title']),'book':lesson['冊'],'lesson':lesson['課'],'appVersion':APP_VERSION,'backendProtocol':BACKEND_PROTOCOL,'quizMode':'practice','availableAt':None,'clozeGrading':'server','availableLanguages':available_langs,'words':words if preview else [{k:v for k,v in x.items() if k!='accepted'} for x in words]}
    # The private registration payload retains reviewed aliases.
    private={'id':id_,'version':version,'title':str(meta['title']),'practiceOpenAt':meta.get('practiceOpenAt') or None,'delayedOpenAt':meta.get('delayedOpenAt') or None,'delayedCloseAt':meta.get('delayedCloseAt') or None,'words':[{'id':x['id'],'word':x['word'],'meaning':x['meaning'],'meanings':x['meanings'],'accepted':x['accepted']} for x in words]}
    return problems,public,private

def course_index(current, new_file):
    files=[str(f) for f in current.get('files',[]) if isinstance(f,str)]
    if new_file not in files:files.append(new_file)
    return {'files':sorted(files)}

def make_export(public,private,files,assets):
    lesson_file=public['id']+'__'+public['version']+'.json'
    base='student/lessons/'
    curr_index=course_index(files,lesson_file)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(base+lesson_file,json.dumps(public,ensure_ascii=False,indent=2))
        z.writestr(base+'index.json',json.dumps(curr_index,ensure_ascii=False,indent=2))
        z.writestr('private/Supabase_register_course.json',json.dumps(private,ensure_ascii=False,indent=2))
        for local,remote in assets.items():z.write(local,remote)
        z.writestr('README_發布說明.txt','僅根目錄 index.html 與 student/ 可發布；private/ 整個資料夾不可公開。手動發布第二課起必須合併 student/lessons/index.json，不可覆蓋舊索引。\n請以教師端 GUI 登錄私人課程資料。\n公開課程 JSON 包含正確答案，僅適合練習與試行，不可當成保密的正式延宕測驗。\n')
    return buf.getvalue(),lesson_file,curr_index


def make_public_export(public,private,files,assets):
    """Public-only archive: no private answer registration or source code."""
    full,lesson_file,index=make_export(public,private,files,assets)
    out=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(full)) as src, zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as dest:
        for name in src.namelist():
            if name=='index.html' or name.startswith('student/'):
                dest.writestr(name,src.read(name))
    return out.getvalue(),lesson_file,index
