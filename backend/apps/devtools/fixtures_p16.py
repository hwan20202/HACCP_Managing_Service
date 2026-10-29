"""P16 S6 개발 콘솔 프리셋 사전 조건 — ADM-PS-07(처음 가져오기 전 → import_roles 결과).

개발 설정에서만(urls가 DEBUG + HACCP_DEV_CONSOLE일 때만 등록).
운영 코드는 이 모듈을 import하지 않는다.

POST /api/dev/fixtures/admin-import {replace?: bool}
  → 200 {before, emptied, report, after, rolled_back: true}
  한 트랜잭션 안에서 문서 권한의 사람을 모두 비운 뒤(새로 옮기는 서버처럼) 개발 역할 파일
  (`apps/staff/roles.json`)을 `import_roles`(F21)로 가져오고, 결과를 읽은 다음 **되돌린다**
  (DB 변화 없음). 명령 `manage.py import_roles`와 같은 서비스 함수를 쓴다.
"""

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.admin_settings import services as adm
from apps.admin_settings import store
from apps.admin_settings.models import RoleFormMember, RoleLeader
from apps.core.http import ApiError, error_response, json_response, parse_json_body
from apps.staff import dev_roles

from .fixtures import _bad

ACTOR_CODE = "DEV-001"


def _people():
    rows = store.role_rows()
    return {
        "version": rows["version"],
        "leaders": len(rows["leaders"]),
        "members": sum(len(f["owners"]) + len(f["writers"]) for f in rows["forms"].values()),
    }


@csrf_exempt
@require_http_methods(["POST"])
def admin_import_fixture(request):
    try:
        body = parse_json_body(request)
        unknown = sorted(set(body) - {"replace"})
        if unknown:
            raise _bad(f"모르는 키: {unknown}")
        with transaction.atomic():
            before = _people()
            RoleLeader.objects.all().delete()
            RoleFormMember.objects.all().delete()
            emptied = _people()
            try:
                replace = bool(body.get("replace"))
                report = adm.import_roles(dev_roles.dev_data(), ACTOR_CODE, replace)
            except adm.ImportFailed as failed:
                raise _bad(f"{failed.message}: {', '.join(failed.lines)}") from None
            after = _people()
            transaction.set_rollback(True)  # 결과만 보고 되돌림(DB 변화 없음)
        return json_response(
            {
                "before": before,
                "emptied": emptied,
                "report": report,
                "after": after,
                "rolled_back": True,
            }
        )
    except ApiError as error:
        return error_response(error)
