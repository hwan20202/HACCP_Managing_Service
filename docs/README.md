# 프로젝트 문서 목차

문서를 사용하는 목적에 따라 전달본·참고 명세·개발 기록으로 나눴습니다. 이사님께서는 [전달 자료](handover/README.md)의 [프로그램 개요](handover/overview.md)부터 읽으시면 됩니다.

| 폴더 | 목적 | 읽는 분 |
|---|---|---|
| [handover/](handover/README.md) | 전달 시점의 기능·사용법·남은 작업·설치·운영 | 이사님·사용자·설치 및 외주 개발자 |
| [reference/](reference/README.md) | 유지보수 때 지킬 업무 규칙·구조·연동 계약 | 후속 개발자 |
| [history/](history/README.md) | 개발 당시 계획·피드백·검증·QA 배포 기록 | 경위나 근거를 찾는 사람 |

## 읽는 순서

1. [프로그램 개요](handover/overview.md)에서 제공 기능과 업무 범위를 확인합니다.
2. [사용 안내](handover/user-guide.md)와 [남은 작업](handover/remaining-work.md)을 확인합니다.
3. 설치 담당자에게 [설치](handover/installation.md)·[운영](handover/operations.md)·[개발 인수인계](handover/developer-guide.md)를 전달합니다.
4. 기능을 수정할 때 참고 명세를 확인하고, 당시 검증 근거가 필요할 때 개발 기록을 봅니다.

## 문서의 기준

- 최종 전달 자료는 ‘설치 완료’나 ‘현업 최종 승인’을 의미하지 않습니다. 대상 환경과 인수 확인 상태는 문서에 별도로 표시합니다.
- reference는 현재 코드·최신 결정과 대조한 기준입니다. 가정과 미확정 사항은 확정 규칙과 구분합니다.
- history는 당시 기록을 보존합니다. 옛 DB 삭제·초기화·샘플 적재·서버 명령을 현재 운영 지시로 사용하지 않습니다.
- 실제 DB·첨부·기준정보는 소스와 별도입니다. [자료 안내](../data/README.md)와 [전달 목록](handover/README.md)을 확인합니다.

실행 개발 환경은 [프로젝트 README](../README.md), 협업 규칙은 [CONTRIBUTING](../CONTRIBUTING.md)을 참고합니다.
