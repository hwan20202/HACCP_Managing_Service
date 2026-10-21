"""P14 역할 설정 테스트 준비물: 임시 설정 파일로 바꿔 끼운다(HACCP_ROLES_FILE).

테스트 설정은 HACCP_ROLES_RELOAD=True라 파일을 바꾸면 다음 호출부터 바로 반영된다.
"""

import copy
import json
import tempfile
from pathlib import Path

from django.test import override_settings

from apps.staff import roles


def default_roles():
    """기본 개발 설정(apps/staff/roles.json)의 사본 — 고쳐서 use_roles에 넘긴다."""
    return copy.deepcopy(json.loads(roles.DEFAULT_FILE.read_text(encoding="utf-8")))


class RolesFileMixin:
    def use_cache(self):
        """운영처럼 설정 파일을 보관본으로(HACCP_ROLES_RELOAD=False). 테스트 끝에 되돌린다.

        메서드 데코레이터 override_settings 안에서 use_roles를 부르면 끝낼 때 순서가 꼬여
        RELOAD=False가 다음 테스트로 새므로, 이 함수로 먼저 켜고 정리도 순서대로 한다.
        """
        override = override_settings(HACCP_ROLES_RELOAD=False)
        override.enable()
        self.addCleanup(override.disable)
        roles.reset()
        self.addCleanup(roles.reset)

    def use_roles(self, data=None, raw=None):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(raw if raw is not None else json.dumps(data, ensure_ascii=False))
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        override = override_settings(HACCP_ROLES_FILE=tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        return Path(tmp.name)
