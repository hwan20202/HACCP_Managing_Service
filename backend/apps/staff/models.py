"""사람 = 수불 `staff` 테이블(C2, D-128). 문서 영역은 이 모듈로만 수불 Staff를 참조한다.

문서 쪽 임시 staff 테이블은 C2에서 없앴다. 이 패키지는 테이블·마이그레이션이 없는 연결 모듈이며
INSTALLED_APPS에 넣지 않는다. 사람 FK는 `inventory.Staff`(PK `id`)를 가리킨다.
"""

from apps.inventory.models import Staff

__all__ = ["Staff"]
