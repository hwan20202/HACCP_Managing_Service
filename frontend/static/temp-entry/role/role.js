// =============================================
// 역할 보기 (P14 ROLE-SC-01, 읽기 전용)
// 설계: dev-notes/roles/p14-s1-screens.md 4장 ROLE-SC-01 · API: p14-s2-spec.md 10.1 GET /api/v1/roles
// P16 묶음 ②: 역할 원본은 DB 문서 권한(ADM-R30) — 저장 즉시 반영(R36). 응답 setup으로 빈 권한 경고(R38).
// 화면은 서버가 계산한 값을 보여 줄 뿐이다(편집은 문서 권한 화면 ADM-SC-03).
// r4(D-198)·r6(D-201): 작성 권한자 열 — 작성·상신을 할 수 있고 결재 칸 후보가 아님
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const BLOCK = {
    no_config: '설정 없음',
    no_candidates: '처리할 사람 없음',
  };
  // 역할 응답의 사람({id, staff_code, name}) — 화면 공통 사람 표시와 같은 모양
  const who = (p) => `<span class="te-person" data-person="${p.id}">${esc(p.name)}<span class="te-person-code">(${esc(p.staff_code)})</span></span>`;
  const whoList = (list) => (list.length ? list.map(who).join(', ') : '<span class="te-hint">(없음)</span>');

  const Roles = {
    title: '역할 보기',
    root: null,

    start(root) {
      this.root = root;
      this.show();
    },

    async show() {
      this.root.innerHTML = `
        <div class="fade-in" id="teRoles">
          ${T.topBar('역할 보기', 'HACCP팀장 · 양식별 담당자·작성 권한자 · 결재 칸 구성 (읽기 전용)', null, { temp: false })}
          <div class="card" id="roBody"><table class="data-table"><tbody>${'<tr class="te-skeleton"><td>.</td><td>.</td><td>.</td><td>.</td></tr>'.repeat(4)}</tbody></table></div>
        </div>`;
      T.bindTopBar(this.root, () => this.show());
      const body = this.root.querySelector('#roBody');
      const r = await api.get('roles');
      if (!this.root.contains(body)) return;
      if (!r.ok) {
        body.innerHTML = `<div class="te-error-box">${esc(T.errorText(r))} <button class="btn btn-secondary btn-sm" id="roRetry">다시 시도</button></div>`;
        body.querySelector('#roRetry').addEventListener('click', () => this.show());
        return;
      }
      body.innerHTML = this.html(r.data);
    },

    html(data) {
      const info = '<div class="te-status-note" id="roInfo">ⓘ 역할은 문서 권한에 저장되며, 바꾸면 다음 작업부터 바로 반영됩니다. 직원 등록·비활성도 바로 반영됩니다.<br>작성 권한자는 작성·상신을 할 수 있습니다 — 결재(칸 처리)·정정 시작·점검자 지정은 담당자·HACCP팀장이 합니다.</div>';
      // R38: 빈 권한 경고(오류와 따로) — 상신할 수 없는 양식이 있을 때만
      const setup = data.setup || { blocked_forms: [] };
      const blocked = setup.blocked_forms || [];
      const setupWarn = blocked.length || setup.empty
        ? `<div class="te-notice" id="roSetup"><strong>문서 권한에 비어 있는 곳이 있습니다 — 상신할 수 없는 양식 ${blocked.length}개</strong>${blocked.length ? `<div class="te-hint">${blocked.map(esc).join(', ')}</div>` : ''}${setup.empty ? '<div class="te-hint">담당자·HACCP팀장이 한 명도 지정되지 않았습니다.</div>' : ''}</div>`
        : '';
      const warnings = data.warnings || [];
      const warn = warnings.length ? `
        <details class="te-role-warnings" id="roWarnings" ${warnings.length <= 3 ? 'open' : ''}>
          <summary>⚠ 경고 ${warnings.length}건</summary>
          <ul>${warnings.map((w) => `<li data-warning="${esc(w.code)}">${esc(w.message)} <span class="te-hint">(${esc(w.code)})</span></li>`).join('')}</ul>
        </details>` : '<div class="te-hint" id="roWarnings">경고 없음</div>';
      const mine = new Set(data.me ? [...data.me.owner_of, ...(data.me.writer_of || [])] : []);
      const slots = (f) => (f.slots.length ? f.slots.map((s) => esc(T.slotLabel(s))).join(' → ') : '<span class="te-hint">설정 없음</span>');
      const rows = data.forms.map((f) => `
        <tr data-form="${esc(f.type_code)}" class="${mine.has(f.type_code) ? 'te-row-mine' : ''}">
          <td><b>${esc(f.type_code)}</b> ${esc(f.name)}</td>
          <td>${slots(f)}</td>
          <td>${whoList(f.owners)}</td>
          <td data-writers>${(f.writers || []).length ? whoList(f.writers) : '<span class="te-hint">–</span>'}</td>
          <td class="te-nowrap">${f.submittable ? '가능' : `<span class="te-judge-ng" title="${esc(BLOCK[f.block_reason] || f.block_reason || '')}">⚠ 불가</span> <span class="te-hint">${esc(BLOCK[f.block_reason] || '')}</span>`}</td>
        </tr>`).join('');
      const me = data.me ? `<div class="te-meta" id="roMe">내 역할: <b>${esc([data.me.is_leader ? 'HACCP팀장' : '', data.me.owner_of.length ? `담당자(${data.me.owner_of.join(', ')})` : '', (data.me.writer_of || []).length ? `작성 권한자(${data.me.writer_of.join(', ')})` : ''].filter(Boolean).join(' · ') || '없음')}</b></div>` : '';
      return `
        ${info}
        ${setupWarn}
        ${warn}
        <div class="te-meta" id="roLeaders" style="margin-top:.75rem"><span>HACCP팀장</span> <b>${whoList(data.leaders)}</b></div>
        <div class="te-table-wrap"><table class="data-table" id="roForms">
          <thead><tr><th>양식</th><th>결재 칸</th><th>담당자</th><th title="작성·상신 — 결재 칸 후보 아님">작성 권한자</th><th>상신</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" class="te-hint">활성 양식이 없습니다.</td></tr>'}</tbody>
        </table></div>
        ${me}`;
    },
  };

  T.register('role-view', Roles);
  window.TempEntryRoles = Roles;
})();
