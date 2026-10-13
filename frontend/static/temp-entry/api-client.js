// =============================================
// 공용 API 클라이언트 (/api/v1/)
// - 사용 화면(temp-entry)과 개발 콘솔이 함께 쓴다.
// - 현재 사용자(X-Staff-Id)는 sessionStorage 'te-staff-id'에 보관한다(T-Q1).
// - 모든 호출을 기록하고 구독자에게 알린다(개발 콘솔 ② 패널).
// =============================================
(function () {
  const STAFF_KEY = 'te-staff-id';
  const listeners = [];
  const log = [];

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
      let payload;
      if (body !== undefined && body !== null) {
        headers['Content-Type'] = 'application/json';
        payload = typeof body === 'string' ? body : JSON.stringify(body);
      }
      const started = performance.now();
      const record = {
        id: log.length + 1,
        at: new Date(),
        request: { method, url, headers: { ...headers }, body: payload === undefined ? null : payload },
      };
      try {
        const response = await fetch(url, { method, headers, body: payload, credentials: 'same-origin' });
        const text = await response.text();
        let data = null;
        try { data = text ? JSON.parse(text) : null; } catch (e) { data = text; }
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
    patch(path, body, options) { return this.request('PATCH', path, body, options); },
    del(path, options) { return this.request('DELETE', path, null, options); },
  };

  window.HaccpApi = HaccpApi;
})();
