"""개발 서버 정적 파일 응답에 no-cache를 붙인다(ISS-001 보완 사이클 R2).

runserver의 StaticFilesHandler는 미들웨어를 거치지 않고 /static/ 을 바로 처리한다.
그래서 헤더는 이 핸들러에서 붙인다. 브라우저는 매번 서버에 확인하고,
바뀌지 않았으면 304를 받는다.
"""

from django.contrib.staticfiles.handlers import StaticFilesHandler


class NoCacheStaticFilesHandler(StaticFilesHandler):
    def serve(self, request):
        response = super().serve(request)
        response["Cache-Control"] = "no-cache"
        return response
