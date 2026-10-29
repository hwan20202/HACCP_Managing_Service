// =============================================
// 공용 API 클라이언트 (/api/v1/)
// - 사용 화면(temp-entry)과 개발 콘솔이 함께 쓴다.
// - 현재 사용자(X-Staff-Id)는 sessionStorage 'te-staff-id'에 보관한다(T-Q1).
// - 모든 호출을 기록하고 구독자에게 알린다(개발 콘솔 ② 패널).
// - P16 R71: 쓰기(GET 밖)는 csrftoken 쿠키 값을 X-CSRFToken에 싣는다(관리 설정 API는 CSRF 검사 유지 —
//   문서 API는 검사를 끄고 있어 영향 없음). 쿠키는 첫 화면이 발급, 검사 실패 403은 안내 문구로 바꿈.
// =============================================
(function () {
  const STAFF_KEY = 'te-staff-id';
  const listeners = [];
  const log = [];

  const CSRF_FAILED = { code: 'CSRF_FAILED', message: '보안 토큰이 만료됐습니다 — 새로고침 후 다시 시도하세요.', details: [] };

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function readStaff() {
    try { return sessionStorage.getItem(STAFF_KEY) || ''; } catch (e) { return ''; }
  }

  const HaccpApi = {
    staffId: readStaff(),
    log,

    setStaff(id) {
      this.staffId = id ? String(id) : '';
      try {
        if (this.staffId) sessionStorage.setItem(STAFF_KEY, this.staffId);
        else sessionStorage.removeItem(STAFF_KEY);
      } catch (e) { /* 저장 실패 시 메모리 값만 사용 */ }
    },

    onCall(fn) { listeners.push(fn); },

    async request(method, path, body, options = {}) {
      const url = path.startsWith('/') ? path : `/api/v1/${path}`;
      const headers = { Accept: 'application/json' };
      const staff = options.staffId !== undefined ? options.staffId : this.staffId;
      if (staff) headers['X-Staff-Id'] = String(staff);
      if (method !== 'GET' && csrfToken()) headers['X-CSRFToken'] = csrfToken();
      let payload;
      let shown = null;
      if (body instanceof FormData) {
        // 스프린트 3 파일 올리기(multipart): Content-Type은 브라우저가 경계값과 함께 채운다
        payload = body;
        shown = `[multipart] ${[...body.entries()].map(([k, v]) => (v instanceof File ? `${k}=${v.name} (${v.size}B)` : `${k}=${v}`)).join(', ')}`;
      } else if (body !== undefined && body !== null) {
        headers['Content-Type'] = 'application/json';
        payload = typeof body === 'string' ? body : JSON.stringify(body);
        shown = payload;
      }
      const started = performance.now();
      const record = {
        id: log.length + 1,
        at: new Date(),
        request: { method, url, headers: { ...headers }, body: shown },
      };
      try {
        const response = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
        // Django CSRF 거부는 JSON이 아닌 403 페이지 — 화면이 읽을 수 있는 공통 오류 모양으로(R71)
        if (response.status === 403 && !(data && typeof data === 'object' && data.code)) data = { ...CSRF_FAILED };
        Object.assign(record, {
          ok: response.ok, status: response.status, statusText: response.statusText,
          data, traceId: response.headers.get('X-Trace-Id'),
          ms: Math.round(performance.now() - started),
        });
      } catch (error) {
        Object.assign(record, {
          ok: false, status: 0, statusText: '네트워크 오류',
          data: { code: 'NETWORK_ERROR', message: '서버에 연결할 수 없습니다.', details: [] },
          ms: Math.round(performance.now() - started),
        });
      }
      log.push(record);
      listeners.forEach((fn) => { try { fn(record); } catch (e) { console.error(e); } });
      return record;
    },

    get(path, options) { return this.request('GET', path, null, options); },
    post(path, body, options) { return this.request('POST', path, body, options); },
    upload(path, formData, options) { return this.request('POST', path, formData, options); },
    patch(path, body, options) { return this.request('PATCH', path, body, options); },
    put(path, body, options) { return this.request('PUT', path, body, options); },
    del(path, options) { return this.request('DELETE', path, null, options); },
  };

  window.HaccpApi = HaccpApi;
})();
