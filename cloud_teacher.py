"""Server-side teacher identity, repository and publication boundary."""
import json
import re
from contextlib import closing

from core import TEXT_PARTS, unique_words

KEY = re.compile(r"[A-Za-z0-9_.-]{1,90}")
SAFE_BRANCH = re.compile(r"codex/vocab-cloud-test-[a-z0-9-]+")


def principal(claims, expected_issuer):
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if expected_issuer and issuer == expected_issuer and isinstance(subject, str) and 0 < len(subject) <= 255:
        return issuer, subject
    raise PermissionError("登入身分不符合教師端設定")


def verify_pooler(settings, project_url):
    match = re.fullmatch(r"https://([a-z0-9-]+)\.supabase\.co/?", project_url)
    if (not match or settings.get("sslmode") != "verify-full"
            or not re.fullmatch(r"[a-z0-9.-]+\.pooler\.supabase\.com", settings.get("host", ""))
            or settings.get("hostaddr")
            or settings.get("port", "5432") != "5432"
            or settings.get("user") != f"vocab_teacher_web.{match[1]}"
            or settings.get("dbname") != "postgres"):
        raise ValueError("Restricted TLS session pooler required")


class PublicationConflict(RuntimeError):
    """An immutable course version already contains different data."""


class TeacherStore:
    def __init__(self, dsn, identity, project_url):
        self.dsn = dsn
        self.identity = identity
        self.project_url = project_url

    def call(self, action, payload=None):
        return self._query("select vocab_teacher.request(%s, %s, %s, %s)", (action,), payload)

    def research(self, filters):
        return self._query("select vocab_teacher.research(%s, %s, %s)", (), filters)

    def _query(self, statement, arguments, payload):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        from psycopg.types.json import Jsonb

        try:
            settings = conninfo_to_dict(self.dsn)
            verify_pooler(settings, self.project_url)
            with closing(psycopg.connect(self.dsn, connect_timeout=5)) as connection:
                with connection.transaction():
                    return connection.execute(
                        statement, (*self.identity, *arguments, Jsonb(payload or {})),
                    ).fetchone()[0]
        except psycopg.Error as error:
            messages = {
                "teacher_denied": "此帳號沒有教師權限",
                "revision_conflict": "已有較新的修訂，請重新載入後再編輯",
                "resource_conflict": "代碼或版本已存在，原有資料保留",
                "publication_conflict": "此版本已綁定不同內容，請使用新的版本號",
            }
            reason = error.diag.message_primary
            if reason == "teacher_denied":
                raise PermissionError(messages[reason]) from None
            if reason == "publication_conflict":
                raise PublicationConflict(messages[reason]) from None
            raise RuntimeError(messages.get(reason, "Supabase 操作未確認，請核對設定並重試")) from None
        except ValueError:
            raise RuntimeError("請使用相同專案、受限帳號及憑證驗證的 Supabase Session Pooler") from None


def read_import(raw, kind):
    if len(raw) > 2_000_000:
        raise ValueError("匯入檔案上限為 2 MB")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError):
        raise ValueError("請使用 UTF-8 JSON") from None
    if kind == "book":
        if not isinstance(doc, list) or not doc or any(
            not isinstance(lesson, dict) or "冊" not in lesson or "課" not in lesson
            or any(not isinstance(lesson.get(part, ""), str)
                   or not isinstance(lesson.get(part + "生詞", []), list) for part in TEXT_PARTS)
            for lesson in doc
        ):
            raise ValueError("教材須包含冊、課及課文格式")
    elif not isinstance(doc, dict) or not isinstance(doc.get("meta"), dict) or not isinstance(doc.get("rows"), list) or any(
        not isinstance(row, dict) for row in doc["rows"]
    ):
        raise ValueError("草稿須包含 meta 與 rows")
    return doc


def new_draft(lesson, parts):
    return {"lesson": {"冊": lesson["冊"], "課": lesson["課"]}, "rows": unique_words(lesson, parts),
            "meta": {"id": "", "version": "v1", "title": ""}}


def validated_publication(settings):
    branch = settings.get("test_branch", "")
    url = settings.get("project_url", "").rstrip("/")
    key = settings.get("publishable_key", "")
    if not SAFE_BRANCH.fullmatch(branch):
        raise ValueError("目前只允許發布到專用測試分支")
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url) or not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key):
        raise ValueError("請設定測試 Supabase URL 與 publishable key")
    return branch, {"projectUrl": url, "publishableKey": key}
