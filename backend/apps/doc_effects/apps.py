from django.apps import AppConfig


class DocEffectsConfig(AppConfig):
    """EFF 문서 후속 처리(D-079): DOC 생명주기 신호를 받아 양식별로 외부 함수를 부른다.

    테이블·마이그레이션 없음. DOC·APR·WF·REQ는 이 앱을 import하지 않는다(P6-NFR-06).
    """

    name = "apps.doc_effects"
    label = "doc_effects"

    def ready(self):
        from apps.documents.signals import document_transitioned

        from . import checks  # 시스템 점검 등록(EFF-C1)
        from .receivers import on_document_transitioned

        document_transitioned.connect(on_document_transitioned, dispatch_uid=checks.DISPATCH_UID)
