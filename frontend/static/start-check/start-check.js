// =============================================
// P16 시작 확인 부품 + 처음 설정 (ADM-R51·R60~R64·R69·R70 — p16-s2-spec 2.6, p16-s1-screens 4.0)
// - 늘 실린다(문서 화면 스크립트 TempEntry·temp-entry.css와 무관 — 문서 화면을 끈 서버에서도 동작).
// - 하는 일: 활성 직원 0명 판정(GET /api/v1/staff — 헤더 없음), 처음 설정 화면, 시작 4상태.
//   현재 사용자 선택은 하지 않는다(문서 화면 머리 선택 상자 그대로 — R50).
// - 상태: loading(불러오는 중) → setup(0명) / ready / failed(다시 시도). App.init의 첫 화면·메뉴 이동·
//   뒤로 가기는 ready일 때만(R70). 0명이면 어느 메뉴를 눌러도 처음 설정(R60).
// - 쓰기는 csrftoken 쿠키 → X-CSRFToken(R71). 현재 사용자 없이 등록(A05)·다시 활성(A08)은
//   서버가 활성 직원 0명일 때만 허용(R62).
// =============================================
(function () {
  const STAFF_KEY = 'te-staff-id';
  const esc = (v) => String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const CSRF_TEXT = '보안 토큰이 만료됐습니다 — 새로고침 후 다시 시도하세요.';
  const FINISHED_TEXT = '이미 직원이 등록되었습니다 — 새로고침 후 화면 머리 "현재 사용자"에서 고르세요.';

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  async function call(method, path, body) {
    const headers = { Accept: 'application/json' };
    if (method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      if (csrfToken()) headers['X-CSRFToken'] = csrfToken();
    }
    try {
      const res = await fetch(`/api/v1/${path}`, {
        method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = null;
      try { data = await res.json(); } catch (e) { data = null; }
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      return { ok: false, status: 0, data: null };
    }
  }

  function errorText(r) {
    if (r.status === 403 && !(r.data && r.data.code)) return CSRF_TEXT;  // Django CSRF 거부(HTML)
    if (r.status === 0) return '서버에 연결할 수 없습니다.';
    const d = r.data || {};
    const codes = (d.details || []).map((x) => x.code);
    if (codes.includes('setup_finished')) return FINISHED_TEXT;
    const first = (d.details || [])[0];
    return first && first.message ? `${first.path ? `${first.path}: ` : ''}${first.message}` : (d.message || `오류 ${r.status}`);
  }

  function rolesText(roles) {
    if (!roles) return '';
    const parts = [];
    if (roles.is_leader) parts.push('HACCP팀장');
    if (roles.owner_of && roles.owner_of.length) parts.push(`담당자(${roles.owner_of.join(', ')})`);
    if (roles.writer_of && roles.writer_of.length) parts.push(`작성 권한자(${roles.writer_of.join(', ')})`);
    return parts.join(' · ');
  }

  const StartCheck = {
    state: 'loading',
    pending: null,    // 준비 전에 누른 메뉴(처음 설정 뒤 그 화면으로 — "원래 화면으로 돌아감")
    onReady: null,
    busy: false,

    ready() { return this.state === 'ready'; },

    container() { return document.getElementById('pageContainer'); },

    // App.init이 부른다. onReady = 첫 화면 그리기·뒤로 가기 설정(원래 init 순서)
    async run(onReady) {
      this.onReady = onReady;
      this.state = 'loading';
      this.drawLoading();
      const r = await call('GET', 'staff');
      if (!r.ok || !r.data || !Array.isArray(r.data.items)) {
        this.state = 'failed';
        this.drawFailed();
        return;
      }
      if (r.data.items.length === 0) {
        this.state = 'setup';
        await this.drawSetup();
        return;
      }
      this.finish();
    },

    // 준비 전 이동 요청(App.navigate가 부름) — 기억만 하고 지금 화면 유지(R60·R70)
    hold(page) {
      if (page && page !== 'dashboard') this.pending = page;
      if (this.state === 'setup') this.focusSetup();
    },

    finish(staffId) {
      this.state = 'ready';
      if (staffId) {
        // R64: 문서 화면 코드가 있으면 메모리 값까지(api-client는 저장값을 로드 때 한 번만 읽음)
        if (window.HaccpApi && typeof window.HaccpApi.setStaff === 'function') window.HaccpApi.setStaff(String(staffId));
        else { try { sessionStorage.setItem(STAFF_KEY, String(staffId)); } catch (e) { /* 메모리만 */ } }
      }
      const go = this.onReady;
      this.onReady = null;
      if (go) go();
      // App은 app.js의 최상위 const(window 속성 아님) — 이름으로 찾는다
      const app = typeof App !== 'undefined' ? App : null;  // eslint-disable-line no-undef
      if (this.pending && app) { const page = this.pending; this.pending = null; app.navigate(page); }
    },

    shell(inner) {
      const c = this.container();
      if (!c) return null;
      c.innerHTML = `<div class="sc-wrap" id="scStart">${inner}</div>`;
      return c.querySelector('#scStart');
    },

    drawLoading() {
      this.shell('<div class="sc-loading" id="scLoading" role="status">불러오는 중…</div>');
    },

    drawFailed() {
      const box = this.shell(`<div class="sc-card sc-error" id="scFailed" role="alert">
        <b>직원 목록을 읽지 못했습니다.</b> 네트워크·서버 상태를 확인한 뒤 다시 시도하세요.
        <div class="sc-actions"><button class="btn btn-secondary btn-sm" id="scRetry">다시 시도</button></div></div>`);
      if (box) box.querySelector('#scRetry').addEventListener('click', () => this.run(this.onReady));
    },

    async drawSetup(message) {
      const [code, inactive] = await Promise.all([call('GET', 'admin/staff/next-code'), call('GET', 'admin/staff?state=inactive')]);
      if (this.state !== 'setup') return;
      const people = inactive.ok && inactive.data ? inactive.data.items : [];
      const rows = people.map((p) => {
        const roles = rolesText(p.roles);
        return `<li class="sc-person" data-staff="${p.id}">
          <span><b>${esc(p.name)}</b> <span class="sc-code">(${esc(p.staff_code)})</span>
          ${roles ? `<span class="sc-roles">문서 권한: ${esc(roles)}</span>` : ''}
          <span class="sc-impact" id="scImpact${p.id}" hidden></span></span>
          <span class="sc-buttons"><button class="btn btn-secondary btn-sm" type="button" data-expand="${p.id}" aria-expanded="false">자세히</button>
          <button class="btn btn-secondary btn-sm" type="button" data-activate="${p.id}">다시 활성</button></span></li>`;
      }).join('');
      const box = this.shell(`<div class="sc-card" id="scSetup">
        <h2 class="sc-title">처음 설정 — 직원을 먼저 등록하세요</h2>
        <p class="sc-hint">활성 직원이 없어 다른 화면을 쓸 수 없습니다. 설치 담당자가 외부 사람이면 본인을 먼저 등록하세요(기록에 실제 작업자가 남습니다).</p>
        <form class="sc-form" id="scForm" autocomplete="off">
          <label class="form-label" for="scName">이름</label>
          <input class="form-control" id="scName" maxlength="40" required>
          <label class="form-label" for="scCode">직원 코드</label>
          <input class="form-control" id="scCode" maxlength="20" required value="${esc(code.ok && code.data ? code.data.code : '')}">
          <button class="btn btn-primary btn-sm" id="scCreate" type="submit">등록</button>
        </form>
        <div class="sc-msg" id="scMsg" role="alert" ${message ? '' : 'hidden'}>${esc(message || '')}</div>
        ${people.length ? `<h3 class="sc-sub">비활성 직원 다시 활성</h3><ul class="sc-list" id="scInactive">${rows}</ul>` : ''}
      </div>`);
      if (!box) return;
      box.querySelector('#scForm').addEventListener('submit', (ev) => { ev.preventDefault(); this.create(); });
      box.querySelectorAll('[data-activate]').forEach((b) => b.addEventListener('click', () => this.activate(Number(b.dataset.activate))));
      box.querySelectorAll('[data-expand]').forEach((b) => b.addEventListener('click', () => this.expand(b)));
      this.focusSetup();
    },

    // R61(r5 Y5): 행을 펼칠 때만 A07(비활성 영향 — 읽기, 헤더 없이)로 문서 권한·대기 결재 수
    async expand(button) {
      const id = Number(button.dataset.expand);
      const box = document.getElementById(`scImpact${id}`);
      if (!box) return;
      const open = button.getAttribute('aria-expanded') !== 'true';
      button.setAttribute('aria-expanded', String(open));
      button.textContent = open ? '접기' : '자세히';
      box.hidden = !open;
      if (!open || box.dataset.loaded) return;
      box.textContent = '확인하는 중…';
      const r = await call('GET', `admin/staff/${id}/impact`);
      if (!r.ok || !r.data) { box.textContent = errorText(r); return; }
      box.dataset.loaded = '1';
      const d = r.data;
      const roles = rolesText(d.roles);
      const lines = [`대기 결재 ${d.pending_approvals}건`];  // 문서 권한은 행에 이미 보임(D-272 C2)
      if (d.pending_checks) lines.push(`개선조치 확인 대기 ${d.pending_checks}건`);
      if (d.inspector_docs) lines.push(`지정 점검자인 작성중 문서 ${d.inspector_docs}건`);
      box.innerHTML = `${esc(lines.join(' · '))}${roles || d.pending_approvals ? '<br>다시 활성하면 이 자격이 살아납니다.' : ''}`;
    },

    focusSetup() {
      const name = document.getElementById('scName');
      if (name) name.focus();
    },

    showError(text) {
      const msg = document.getElementById('scMsg');
      if (!msg) return;
      msg.hidden = false;
      msg.innerHTML = `${esc(text)} <button class="btn btn-secondary btn-sm" id="scReload" type="button">새로고침</button>`;
      msg.querySelector('#scReload').addEventListener('click', () => window.location.reload());
    },

    setBusy(on) {
      this.busy = on;
      document.querySelectorAll('#scSetup button').forEach((b) => { b.disabled = on; });
    },

    async create() {
      if (this.busy) return;
      const name = document.getElementById('scName').value;
      const code = document.getElementById('scCode').value;
      this.setBusy(true);
      const r = await call('POST', 'admin/staff', { name, staff_code: code });
      this.setBusy(false);
      if (!r.ok) { this.showError(errorText(r)); return; }
      this.done(r.data.staff);
    },

    async activate(id) {
      if (this.busy) return;
      this.setBusy(true);
      const r = await call('POST', `admin/staff/${id}/active`, { active: true });
      this.setBusy(false);
      if (!r.ok) { this.showError(errorText(r)); return; }
      this.done(r.data.staff, '다시 활성했습니다');
    },

    done(staff, verb = '등록했습니다') {
      const c = this.container();
      if (c) c.innerHTML = '';
      this.finish(staff.id);
      if (window.TempEntry && typeof window.TempEntry.reloadPeople === 'function') window.TempEntry.reloadPeople();
      const note = document.createElement('div');
      note.className = 'sc-toast';
      note.setAttribute('role', 'status');
      note.textContent = `${staff.name}(${staff.staff_code}): ${verb} — 현재 사용자로 선택했습니다.`;
      document.body.appendChild(note);
      setTimeout(() => note.remove(), 5000);
    },
  };

  window.StartCheck = StartCheck;
})();
