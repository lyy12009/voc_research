"""Publish only allowlisted student files, using a single non-force Git ref update."""
import base64, http.client, json, re, time, urllib.request, urllib.error
from pathlib import Path
OWNER='lyy12009'; REPO='voc_research'; BRANCH='codex/vocab-cloud-test-synthetic'
BASE=f'https://api.github.com/repos/{OWNER}/{REPO}'
SITE=f'https://{OWNER}.github.io/{REPO}/'
ASSETS={'index.html','student/index.html','student/app.js','student/style.css'}
INDEX='student/lessons/index.json'
BACKEND='student/backend.json'
class GitHubError(RuntimeError):
    def __init__(self, status, message):
        self.status=status
        super().__init__(f'GitHub HTTP {status}：{message}')

def request(method,path,token,payload=None,missing=False,base=BASE):
    if not token: raise ValueError('尚未設定 GitHub Token')
    data=json.dumps(payload,ensure_ascii=False).encode('utf-8') if payload is not None else None
    req=urllib.request.Request(base+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'VocabResearch-Teacher','Content-Type':'application/json'})
    retryable=method=='GET' or (method=='POST' and path in ('/git/blobs','/git/trees','/git/commits'))
    for attempt in range(2 if retryable else 1):
        try:
            with urllib.request.urlopen(req,timeout=25) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if missing and error.code==404:
                return None
            if not (retryable and attempt==0 and error.code in (502,503,504)):
                messages={401:'Token 無效或已過期',403:'權限不足、限制或分支保護',
                          404:'找不到資源或 Token 未獲授權',409:'倉庫尚未初始化或發生衝突',
                          422:'資料驗證失敗、分支限制或其他提交同時更新'}
                raise GitHubError(error.code,messages.get(error.code,'API 請求未成功')) from None
        except (urllib.error.URLError,TimeoutError,http.client.HTTPException,ConnectionError):
            if not retryable or attempt:
                raise RuntimeError('GitHub 網路連線中斷，重新確認分支後可安全重試') from None
        time.sleep(0.5)


def connection(token):
    user=request('GET','/user',token,base='https://api.github.com')
    repo=request('GET','',token)
    if repo.get('full_name','').lower()!=f'{OWNER}/{REPO}'.lower():raise ValueError('倉庫不符')
    perm=repo.get('permissions',{})
    if perm.get('push') is False:raise ValueError('目前登入身分沒有此倉庫寫入權限')
    if repo.get('archived') or repo.get('disabled'):raise ValueError('倉庫已封存或停用')
    return {'login':user.get('login',''), 'default_branch':repo.get('default_branch',''), 'push':perm.get('push'), 'private':repo.get('private'), 'has_pages':repo.get('has_pages')}

def branch_path(branch):
    if not re.fullmatch(r'codex/vocab-cloud-test-[a-z0-9-]{1,60}',branch):
        raise ValueError('發布目標須為既有的 codex/ 開發分支')
    return '/git/refs/heads/'+branch


def head(token,branch=BRANCH):
    try:return request('GET',branch_path(branch).replace('/refs/','/ref/',1),token,missing=True)
    except GitHubError as e:
        if e.status==409:return None
        raise

def read_at(path,token,ref):
    result=request('GET','/contents/'+path+'?ref='+ref,token,missing=True)
    if result is None:return None
    if result.get('type')!='file' or result.get('encoding')!='base64':raise ValueError('無法安全讀取 '+path)
    return base64.b64decode(result['content'])

def load_index(token,ref):
    raw=read_at(INDEX,token,ref)
    if raw is None:return {'files':[]}
    obj=json.loads(raw.decode('utf-8'))
    if not isinstance(obj,dict) or not isinstance(obj.get('files'),list) or not all(isinstance(x,str) and re.fullmatch(r'[A-Za-z0-9_.-]+\.json',x) for x in obj['files']):raise ValueError('既有課程索引格式不正確，已停止以避免遺失資料。')
    hidden=obj.get('hidden',[])
    if not isinstance(hidden,list) or any(not isinstance(x,str) or x not in obj['files'] for x in hidden) or len(hidden)!=len(set(hidden)):
        raise ValueError('既有隱藏版本清單格式不正確，已停止操作以避免更改資料。')
    return obj

def set_visibility(token,lesson_file,visible,branch=BRANCH):
    """Only change the public index. Does not delete JSON or change backend authorization."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',lesson_file):
        raise ValueError('課程版本檔名不合法')
    h=head(token,branch)
    if not h: raise ValueError('找不到發布目標開發分支')
    parent=h['object']['sha']
    idx=load_index(token,parent)
    if lesson_file not in idx['files']:raise ValueError('此版本不在已發布課程清單中')
    hidden=set(idx.get('hidden',[]))
    old_visible=lesson_file not in hidden
    if old_visible==bool(visible):return {'changed':False,'visible':old_visible,'files':idx['files'],'hidden':idx.get('hidden',[])}
    if visible:hidden.discard(lesson_file)
    else:hidden.add(lesson_file)
    updated=dict(idx)
    updated['hidden']=[x for x in idx['files'] if x in hidden]
    commit_changes(token,branch,parent,{INDEX:encode_json(updated)},
                   ('Show' if visible else 'Hide')+' vocabulary lesson '+lesson_file)
    return {'changed':True,'visible':bool(visible),'files':idx['files'],'hidden':updated['hidden']}

def status(token,branch=BRANCH):
    info=connection(token); h=head(token,branch)
    info['initialized']=bool(h)
    idx=load_index(token,h['object']['sha']) if h else {'files':[],'hidden':[]}
    info['files']=idx['files']
    info['hidden']=idx.get('hidden',[])
    return info

def encode_json(obj):
    return json.dumps(obj,ensure_ascii=False,indent=2).encode('utf-8')


def public_backend(config):
    from teacher_backend import public_config
    safe=public_config(config.get('projectUrl',''),config.get('publishableKey',''))
    return encode_json(safe)


def commit_changes(token,branch,parent,changes,message):
    if not changes:
        return parent
    commit=request('GET','/git/commits/'+parent,token)
    entries=[]
    for path,raw in changes.items():
        blob=request('POST','/git/blobs',token,{'content':base64.b64encode(raw).decode('ascii'),'encoding':'base64'})
        entries.append({'path':path,'mode':'100644','type':'blob','sha':blob['sha']})
    tree=request('POST','/git/trees',token,{'base_tree':commit['tree']['sha'],'tree':entries})
    new=request('POST','/git/commits',token,{'message':message,'tree':tree['sha'],'parents':[parent]})
    try:
        request('PATCH',branch_path(branch),token,{'sha':new['sha'],'force':False})
    except GitHubError:
        raise
    except RuntimeError:
        ref=head(token,branch)
        current=(ref or {}).get('object',{}).get('sha')
        if current==new['sha']:
            return current
        if current!=parent:
            raise RuntimeError('GitHub 分支已變動，請重新讀取分支後重試') from None
        request('PATCH',branch_path(branch),token,{'sha':new['sha'],'force':False})
    return new['sha']


def publication_base(token,branch):
    info=connection(token)
    if info['private']:
        raise ValueError('此流程以公開的學生端儲存庫為目標')
    ref=head(token,branch)
    if not ref:
        raise ValueError('找不到發布目標開發分支')
    return ref['object']['sha']


def shared_changes(token,parent,student_assets,backend):
    if set(student_assets.values())!=ASSETS:
        raise ValueError('學生端資源清單不符')
    changes={}
    for local,remote in student_assets.items():
        raw=Path(local).read_bytes()
        if token.encode() in raw:
            raise ValueError('偵測到憑證出現在公開程式')
        old=read_at(remote,token,parent)
        if old!=raw:
            changes[remote]=raw
    config=public_backend(backend)
    existing=read_at(BACKEND,token,parent)
    if existing is not None:
        old_url=json.loads(existing).get('projectUrl')
        if old_url!=json.loads(config)['projectUrl']:
            raise ValueError('此分支已綁定另一個 Supabase 專案')
    if existing!=config:
        changes[BACKEND]=config
    return changes


def update_student_site(token,student_assets,backend,branch=BRANCH):
    parent=publication_base(token,branch)
    changes=shared_changes(token,parent,student_assets,backend)
    commit_changes(token,branch,parent,changes,'Update VocabResearch shared student site')
    return {'changed':bool(changes),'files':list(changes)}


def publish(token,public,student_assets,backend,branch=BRANCH):
    """Publish only reviewed student files to an existing development branch."""
    from core import course_index
    for key in ('id','version'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,90}',str(public.get(key,''))):
            raise ValueError('課程 ID 或版本格式不合法')
    word_fields={'id','word','pinyin','meaning','meanings','sentence','category','source'}
    course_fields={'schema','id','version','title','book','lesson','appVersion','backendProtocol',
                   'quizMode','availableAt','clozeGrading','availableLanguages','words'}
    if set(public)-course_fields or any(set(word)-word_fields for word in public['words']):
        raise ValueError('公開教材包含非允許欄位')
    raw=encode_json(public)
    if token.encode() in raw or re.search(rb'(?:sb_secret_|github_pat_|ghp_)[A-Za-z0-9_-]{12,}',raw):
        raise ValueError('公開教材含有疑似憑證')
    lesson_file=public['id']+'__'+public['version']+'.json'
    lesson_path='student/lessons/'+lesson_file
    parent=publication_base(token,branch)
    idx=load_index(token,parent)
    existing=read_at(lesson_path,token,parent)
    if (existing is not None and json.loads(existing)!=public) or (lesson_file in idx['files'] and existing is None):
        raise ValueError('GitHub 已有同名但不同內容的版本，請提高版號')
    changes=shared_changes(token,parent,student_assets,backend)
    new_index=dict(idx);new_index.update(course_index(idx,lesson_file))
    if existing is None:
        changes[lesson_path]=raw
    if new_index!=idx:
        changes[INDEX]=encode_json(new_index)
    commit_changes(token,branch,parent,changes,'Publish vocabulary lesson '+lesson_file)
    return lesson_path,new_index
