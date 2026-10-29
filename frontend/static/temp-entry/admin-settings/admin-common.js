// =============================================
// P16 관리 설정 공통 — ADM-SC-04 변경 이력 창(p16-s1-screens 6장) · 사람 칩 · 오류 문구
// 직원 관리(staff-admin.js)·문서 권한(role/role.js)이 쓴다. 품목별 CCP(item-ccp.js)는 자기 창을 그대로 씀.
// =============================================
(function () {
  const T = window.TempEntry;
  const esc = (v) => T.esc(v);

  const Admin = {
    // 처음 설정으로 처리된 동작은 따로 표시(R63)
    STAFF_ACTIONS: {
      create: '등록', bootstrap_create: '등록(처음 설정으로 처리됨)', rename: '이름 수정',
      deactivate: '비활성', activate: '다시 활성', bootstrap_activate: '다시 활성(처음 설정으로 처리됨)',
    },
    ROLE_NAMES: { owner: '담당자', writer: '작성 권한자' },

    // 오류 + details 메시지(검사 오류는 VALIDATION_ERROR + details[].code — 공통 형식)
    errorText(r) {
      const d = (r && r.data) || {};
      const more = (d.details || []).filter((x) => x.message).map((x) => `${x.path ? `${x.path}: ` : ''}${x.message}`);
      return more.length ? more.join(' · ') : T.errorText(r);
    },

    // 사람 칩(문서 권한 응답 {id, staff_code, name, is_active}) — 비활성 = 점선·취소선(효과 없음)
    chip(p, { removable = false, added = false } = {}) {
      const off = p.is_active === false;
      const cls = `te-ad-chip${off ? ' te-ad-chip-off' : ''}${added ? ' te-ad-chip-new' : ''}`;
      const title = off ? '비활성 — 효과 없음(문서 권한에는 남아 있음)' : (added ? '이번에 넣음(저장 전)' : '');
      return `<span class="${cls}" data-chip="${p.id}"${title ? ` title="${esc(title)}"` : ''}>${esc(p.name)} <span class="te-person-code">${esc(p.staff_code)}</span>${removable ? ` <button type="button" class="te-ad-x" data-remove="${p.id}" aria-label="${esc(p.name)} 빼기">×</button>` : ''}</span>`;
    },

    // ADM-SC-04: [{at, actor, label, action, before, after}] → 창
    historyModal(title, head, rows) {
      const wrap = document.createElement('div');
      wrap.className = 'te-modal-wrap';
      wrap.innerHTML = `<div class="te-modal te-pl-modal-wide" role="dialog" aria-modal="true">
        <div class="modal-header"><div class="modal-title">변경 이력 — ${esc(title)}</div></div>
        <div class="te-modal-body"><div class="te-table-wrap"><table class="data-table" id="adHist"><thead><tr>${head.map((h) => `<th>${esc(h)}</th>`).join('')}</tr></thead>
          <tbody>${rows || `<tr><td colspan="${head.length}" class="te-empty">이력이 없습니다.</td></tr>`}</tbody></table></div>
        <div class="te-modal-footer"><button class="btn btn-secondary" data-close>닫기</button></div></div></div>`;
      document.body.appendChild(wrap);
      wrap.addEventListener('click', (ev) => { if (ev.target === wrap) wrap.remove(); });
      wrap.querySelector('[data-close]').addEventListener('click', () => wrap.remove());
      wrap.querySelector('[data-close]').focus();
    },

    actorName(x) {
      return x.actor && x.actor.name ? x.actor.name : `#${x.actor && x.actor.id}`;
    },

    // 직원 관리·문서 권한 저장 뒤 화면 공통 직원·역할 캐시 다시 읽기(R52 — Q3 a)
    async refreshPeople() {
      T.reloadPeople();
      await T.loadStaff();
      T.refreshBadges();
    },
  };

  window.TempEntryAdmin = Admin;
})();
