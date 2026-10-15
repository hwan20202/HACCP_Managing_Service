"""문서 첨부 파일 (F14~F18, p4-s2-spec 4장·p4-s2-flows 6장, 구현 기준 document-files/s4-basis.md).

- 저장 위치: ``MEDIA_ROOT/files/YYYY/MM/<무작위 이름>`` (F-002 Q1 — 백업·복원 대상 ``uploads/``).
  DB의 ``storage_path``는 ``MEDIA_ROOT`` 기준 상대 경로. 원래 이름은 DB에만 둔다(DOC-NFR-11).
- 파일을 고칠 수 있는 상태 = ``EDITABLE``(P6: 정정 중 포함). 올리기·연결·끊기는 모두 문서 버전 +1
  → 정정 시작 뒤 파일을 건드리면 정정 취소가 막힌다(D-075).
- 쓰기는 트랜잭션의 첫 SQL을 문서 조건부 UPDATE로 한다(DOC-NFR-09). 올리기의 실제 파일 쓰기는
  DB 잠금을 오래 잡지 않으려고 트랜잭션 **밖에서 먼저** 하고, 실패하면 지운다(DOC-FUP-06a).
  끊기로 파일을 지울 때는 **커밋 뒤** 실제 파일을 지운다(DOC-FDT-05).
- 상신 잠금 때 보존 표시(DOC-LCK-01b)는 ``services.lock_for_review`` 안에 있다.
- 이 모듈은 결재·워크플로우를 import하지 않는다.
"""

import hashlib
import secrets
from datetime import timedelta
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef
from django.utils import timezone

from apps.core.trace import step

from . import errors
from .models import FILE_MAX_BYTES, DocSection, Document, DocumentFile, DocumentTemplate, File
from .services import (
    EDITABLE,
    PAGE_SIZE,
    _iso,
    _item_names,
    _lock_failure,
    _refs_by_document,
    _target_summary,
)

FILE_EDITABLE = EDITABLE  # p4-s2-spec 3장 — P6 이후 {draft, rejected, correcting}
NAME_MAX = 255
SEARCH_TEXT_MAX = 50
SEARCH_DAYS_DEFAULT, SEARCH_DAYS_MAX = 90, 365

# 확장자 → (MIME, 파일 앞부분 서명). 확장자와 서명이 모두 맞아야 한다(DOC-VR-20).
_PDF = ("application/pdf", (b"%PDF-",))
_JPEG = ("image/jpeg", (b"\xff\xd8\xff",))
_PNG = ("image/png", (b"\x89PNG\r\n\x1a\n",))
KINDS = {".pdf": _PDF, ".jpg": _JPEG, ".jpeg": _JPEG, ".png": _PNG}
_SIGNATURE_BYTES = 8


def media_root():
    return Path(settings.MEDIA_ROOT)


def _absolute(storage_path):
    return media_root() / PurePosixPath(storage_path)


def file_row(file):
    return {
        "file_id": file.file_id,
        "original_name": file.original_name,
        "mime_type": file.mime_type,
        "size_bytes": file.size_bytes,
        "uploaded_by": file.uploaded_by_id,
        "uploaded_at": _iso(file.uploaded_at),
        "retained": file.retained_at is not None,
    }


def _rejected(reason, message):
    return errors.FileRejected(
        details=[{"path": "file", "code": reason, "reason": reason, "message": message}]
    )


def _check_upload(upload):
    """DOC-FUP-02 이름 → 크기 → 형식 순서. 반환: mime_type."""
    name = Path(upload.name or "").name
    if not name or len(name) > NAME_MAX:
        raise _rejected("name", f"파일 이름은 1~{NAME_MAX}자여야 합니다.")
    if not upload.size or upload.size > FILE_MAX_BYTES:
        raise _rejected("size", "파일은 20MB 이하여야 합니다.")
    kind = KINDS.get(Path(name).suffix.lower())
    if kind is None:
        raise _rejected("type", "PDF·JPG·PNG 파일만 올릴 수 있습니다.")
    upload.seek(0)
    head = upload.read(_SIGNATURE_BYTES)
    upload.seek(0)
    mime, signatures = kind
    if not any(head.startswith(sig) for sig in signatures):
        raise _rejected("type", "파일 내용이 확장자와 맞지 않습니다.")
    return name, mime


def _write(upload, now):
    """DOC-FUP-03: 무작위 이름으로 쓰고 sha256을 계산한다. 반환: (storage_path, sha256, 크기)."""
    ext = Path(upload.name).suffix.lower()
    relative = PurePosixPath("files", f"{now:%Y}", f"{now:%m}", f"{secrets.token_hex(16)}{ext}")
    target = _absolute(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, size = hashlib.sha256(), 0
    with open(target, "xb") as out:  # 이름 충돌이면 덮어쓰지 않고 실패
        for chunk in upload.chunks():
            digest.update(chunk)
            size += len(chunk)
            out.write(chunk)
    target.chmod(0o600)
    return str(relative), digest.hexdigest(), size


def _remove(storage_path):
    try:
        _absolute(storage_path).unlink()
    except FileNotFoundError:
        pass


def _lock(document_id, expected_version, step_id, now):
    """FUP-04·FLK-02·FDT-02: 문서 조건부 UPDATE(첫 SQL). 0행이면 404/409 사유를 가린다."""
    with step(step_id, "DOC", "문서 잠금(조건부 UPDATE)") as s:
        changed = Document.objects.filter(
            pk=document_id,
            deleted_at__isnull=True,
            status__in=FILE_EDITABLE,
            version=expected_version,
        ).update(updated_at=now, version=F("version") + 1)
        s.note(f"영향 행 {changed}")
    if changed == 0:
        _lock_failure(
            document_id, f"{step_id}a", expected_version=expected_version, allowed=FILE_EDITABLE
        )


def _require_files_rule(document_id, step_id):
    with step(step_id, "DOC", "양식의 파일 사용 확인") as s:
        document = Document.objects.select_related("template").get(pk=document_id)
        if "files" not in (document.template.schema_json or {}):
            s.fail(document.template.type_code)
            raise errors.FilesNotAllowed()
        return document


def _version(document_id):
    return Document.objects.filter(pk=document_id).values_list("version", flat=True).get()


# ---------------------------------------------------------------- F14 올리기


def attach_file(actor_id, document_id, expected_version, upload):
    """F14 파일 1개를 올려 이 문서에 연결한다. 반환: {file, document_version}."""
    with step("DOC-FUP-02", "DOC", "파일 검사(이름·크기·형식)") as s:
        try:
            name, mime = _check_upload(upload)
        except errors.FileRejected as error:
            s.fail(error.details[0]["reason"])
            raise
    now = timezone.now()
    with step("DOC-FUP-03", "DOC", "실제 파일 쓰기(트랜잭션 밖)") as s:
        storage_path, sha256, size = _write(upload, now)
        s.note(storage_path)
    try:
        with transaction.atomic():
            _lock(document_id, expected_version, "DOC-FUP-04", now)
            _require_files_rule(document_id, "DOC-FUP-05")
            with step("DOC-FUP-06", "DOC", "file·document_file 저장"):
                file = File.objects.create(
                    storage_path=storage_path,
                    original_name=name,
                    mime_type=mime,
                    size_bytes=size,
                    sha256=sha256,
                    uploaded_by_id=actor_id,
                    uploaded_at=now,
                )
                DocumentFile.objects.create(
                    document_id=document_id, file=file, linked_by_id=actor_id, linked_at=now
                )
    except BaseException:
        with step("DOC-FUP-06a", "DOC", "방금 쓴 파일 삭제(DB 반영 실패)"):
            _remove(storage_path)
        raise
    return {"file": file_row(file), "document_version": _version(document_id)}


# ---------------------------------------------------------------- F15 연결


def link_file(actor_id, document_id, expected_version, file_id):
    """F15 다른 문서의 기존 파일을 복사 없이 연결한다. 같은 유형 문서의 파일만(F-002 Q3)."""
    now = timezone.now()
    with transaction.atomic():
        _lock(document_id, expected_version, "DOC-FLK-02", now)
        document = _require_files_rule(document_id, "DOC-FLK-03")
        with step("DOC-FLK-04", "DOC", "파일·연결 문서 유형 확인") as s:
            file = File.objects.filter(pk=file_id).first()
            if file is None:
                s.fail("파일 없음")
                raise errors.FileNotFound()
            types = set(
                DocumentFile.objects.filter(file_id=file_id).values_list(
                    "document__template__type_code", flat=True
                )
            )
            # 연결 문서가 없는 파일(보존 표시만 남은 파일)도 유형을 알 수 없어 거부(F-002 Q3)
            if types != {document.template.type_code}:
                s.fail(f"유형 {sorted(types)} ≠ {document.template.type_code}")
                raise errors.FileTemplateMismatch(
                    details=[
                        {
                            "path": "link_file_id",
                            "code": "template_mismatch",
                            "message": "같은 종류 문서의 파일만 연결할 수 있습니다.",
                            "file_types": sorted(types),
                        }
                    ]
                )
        with step("DOC-FLK-05", "DOC", "document_file 저장") as s:
            try:
                with transaction.atomic():
                    DocumentFile.objects.create(
                        document_id=document_id, file=file, linked_by_id=actor_id, linked_at=now
                    )
            except IntegrityError:
                s.fail("이미 연결됨")
                raise errors.FileAlreadyLinked() from None
    return {"file": file_row(file), "document_version": _version(document_id)}


# ---------------------------------------------------------------- F16 끊기


def detach_file(actor_id, document_id, expected_version, file_id):
    """F16 연결을 끊는다. 어디에도 연결되지 않고 보존 표시도 없으면 파일까지 지운다(DOC-FR-24)."""
    now = timezone.now()
    with transaction.atomic():
        _lock(document_id, expected_version, "DOC-FDT-02", now)
        with step("DOC-FDT-03", "DOC", "연결 삭제") as s:
            deleted, _ = DocumentFile.objects.filter(
                document_id=document_id, file_id=file_id
            ).delete()
            s.note(f"영향 행 {deleted}")
            if deleted == 0:
                raise errors.FileNotLinked()
        with step("DOC-FDT-04", "DOC", "남은 연결·보존 표시 확인") as s:
            # 논리 삭제된 문서의 연결도 센다(F-002 Q4)
            remaining = DocumentFile.objects.filter(file_id=file_id).count()
            file = File.objects.get(pk=file_id)
            s.note(f"남은 연결 {remaining}, 보존 {'있음' if file.retained_at else '없음'}")
        if remaining == 0 and file.retained_at is None:
            with step("DOC-FDT-05", "DOC", "파일 행 삭제(실제 파일은 커밋 뒤)"):
                storage_path = file.storage_path
                File.objects.filter(pk=file_id).delete()
                transaction.on_commit(lambda: _remove(storage_path))
    return {"document_version": _version(document_id)}


# ---------------------------------------------------------------- F17 보기


def open_file(file_id):
    """F17 반환: (절대 경로, 원래 이름, MIME). DB에 있어도 실제 파일이 없으면 FileNotFound."""
    file = File.objects.filter(pk=file_id).first()
    if file is None:
        raise errors.FileNotFound()
    path = _absolute(file.storage_path)
    if not path.is_file():
        raise errors.FileNotFound(details=[{"path": "file", "code": "missing_on_disk"}])
    return path, file.original_name, file.mime_type


# ---------------------------------------------------------------- F18 검색


def _search_filters(filters):
    """DOC-VR-24. 반환: (type_code, item, supplier, days, page)."""
    problems = []

    def bad(path, message):
        problems.append({"path": path, "code": "invalid", "message": message})

    type_code = (filters.get("type_code") or "").strip()
    if not type_code:
        bad("type_code", "양식 종류가 필요합니다.")
    else:
        schemas = DocumentTemplate.objects.filter(type_code=type_code).values_list(
            "schema_json", flat=True
        )
        if not any("files" in (schema or {}) for schema in schemas):
            bad("type_code", "파일을 쓰는 양식이 아닙니다.")
    texts = {}
    for key in ("item", "supplier"):
        value = (filters.get(key) or "").strip()
        if len(value) > SEARCH_TEXT_MAX:
            bad(key, f"{SEARCH_TEXT_MAX}자 이하로 입력하세요.")
        texts[key] = value
    numbers = {}
    for key, default, low, high in (
        ("days", SEARCH_DAYS_DEFAULT, 1, SEARCH_DAYS_MAX),
        ("page", 1, 1, None),
    ):
        raw = str(filters.get(key) or "").strip()
        if raw == "":
            numbers[key] = default
            continue
        if not (raw.isascii() and raw.isdigit()) or int(raw) < low or (high and int(raw) > high):
            bad(key, f"{low}~{high} 사이 정수" if high else f"{low} 이상 정수")
            continue
        numbers[key] = int(raw)
    if problems:
        raise errors.InvalidFilter(details=problems)
    return type_code, texts["item"], texts["supplier"], numbers["days"], numbers["page"]


def search_files(filters):
    """F18 같은 유형 문서의 이전 파일을 품명·매입처·기간으로 찾는다(최신순, 20개씩)."""
    with step("DOC-FSR-01", "DOC", "필터 검사") as s:
        try:
            type_code, item, supplier, days, page = _search_filters(filters)
        except errors.InvalidFilter as error:
            s.fail(f"오류 {len(error.details)}건")
            raise
    with step("DOC-FSR-02", "DOC", "파일·연결 문서 조회"):
        documents = Document.objects.filter(template__type_code=type_code, deleted_at__isnull=True)
        for key, field in (("item_name", item), ("supplier_name", supplier)):
            if field:
                documents = documents.filter(
                    Exists(
                        DocSection.objects.filter(
                            document_id=OuterRef("pk"),
                            section_def="info",
                            **{f"values_json__{key}__icontains": field},
                        )
                    )
                )
        since = timezone.now() - timedelta(days=days)
        files = File.objects.filter(
            Exists(DocumentFile.objects.filter(file_id=OuterRef("pk"), document__in=documents)),
            uploaded_at__gte=since,
        )
        total = files.count()
        offset = (page - 1) * PAGE_SIZE
        page_files = list(files.order_by("-uploaded_at", "-file_id")[offset : offset + PAGE_SIZE])
        links = list(
            DocumentFile.objects.filter(
                file_id__in=[f.file_id for f in page_files], document__deleted_at__isnull=True
            )
            .select_related("document")
            .order_by("document_id")
        )
        doc_ids = sorted({link.document_id for link in links})
        refs = _refs_by_document(doc_ids) if doc_ids else {}
        names = _item_names(doc_ids)
        by_file = {}
        for link in links:
            d = link.document
            by_file.setdefault(link.file_id, []).append(
                {
                    "document_id": d.document_id,
                    "status": d.status,
                    "work_date": d.work_date.isoformat() if d.work_date else None,
                    "target_summary": _target_summary(
                        d, refs.get(d.document_id, []), names.get(d.document_id)
                    ),
                }
            )
        return {
            "items": [{**file_row(f), "documents": by_file.get(f.file_id, [])} for f in page_files],
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
        }
