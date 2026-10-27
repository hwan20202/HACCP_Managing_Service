# Windows 11 운영

운영 구성은 Caddy → Waitress → Django → SQLite입니다.
설치 순서와 HTTPS·서비스·백업 절차는 [배포 안내](../../docs/handover/installation.md)를 따릅니다.

- `scripts/windows_services.py`: 대상 Windows에서 절대 경로가 반영된 WinSW XML 생성
- `tools/services/haccp-app.xml`: Waitress 서비스 (생성 파일, Git 제외)
- `tools/services/haccp-proxy.xml`: Caddy 서비스 (생성 파일, Git 제외)
- `infra/caddy/Caddyfile`: Ubuntu 샌드박스와 Windows가 공유하는 프록시 설정

WinSW 바이너리는 생성된 XML과 같은 이름의 `.exe`로 배치합니다.
소스 폴더를 옮기거나 가상환경을 다시 만들면 서비스를 중지한 뒤 XML을 다시 생성합니다.
이 저장소에 설치·시작 시 자동으로 시스템 설정을 바꾸는 코드는 없습니다.

