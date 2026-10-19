// =============================================
// P11 CCP 대시보드 (DSH-SC-01) · 개선조치 확인 창 (DSH-SC-02)
// - dev-notes/dashboard/p11-s1-screens.md 3·4장, p11-s2-spec.md 4장
// - REQ-A09 GET /api/v1/ccp-dashboard 와 DOC-A22 GET /api/v1/deviations/pending 을 따로 부른다
//   (한 구역 실패가 다른 구역을 막지 않음 — S1b 3.5). 현재 사용자가 없으면 헤더 없이 부른다.
// - 확인: DOC-A23 POST /api/v1/deviations/{id}/check. 문서 상세(DOC-SC-04)도 이 창을 쓴다.
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);

  const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];
  const dow = (day) => WEEKDAY[new Date(`${day}T00:00:00Z`).getUTCDay()];
  const seoulDay = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  const hhmm = () => new Date().toLocaleTimeString('sv-SE', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit' });
  const md = (day) => (day ? day.slice(5) : '');
  const num = (n) => (typeof n === 'number' ? n.toLocaleString('ko-KR') : esc(n));
  const fmtMinutes = (m) => (typeof m === 'number' ? `${Math.floor(m / 60)}시간 ${m % 60}분` : esc(m));
  const CARD_ORDER = ['CCP-1P', 'CCP-2B', 'CCP-3P'];  // 서버 순서와 같음(카드 순서 고정)

  // 측정 시각: 기준일과 같은 날이면 HH:MM, 아니면 MM-DD HH:MM (S1b 3.2)
  function atText(at, base) {
    if (!at) return '';
    const [day, time] = String(at).split('T');
    return day === base ? (time || '').slice(0, 5) : `${md(day)} ${(time || '').slice(0, 5)}`;
  }
  // 지난 시간(기준일이 오늘일 때만 — S1a-Q3 a). 측정 시각은 Asia/Seoul 벽시계 값(오프셋 없음)
  function agoText(iso) {
    if (!iso) return '';
    const t = /[zZ]|[+-]\d\d:\d\d$/.test(iso) ? new Date(iso) : new Date(`${iso}${iso.length <= 16 ? ':00' : ''}+09:00`);
    const min = Math.floor((Date.now() - t.getTime()) / 60000);
    if (Number.isNaN(min)) return '';
    if (min < 0) return '';
    if (min < 1) return '방금';
    if (min < 60) return `${min}분 전`;
    if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
    return `${Math.floor(min / 1440)}일 전`;
  }

  // 최근 측정 값(S1b 3.2): 1P 자력·청소, 2B 온도·시간, 3P 9칸이 모두 기준대로면 "정상", 아니면 어긋난 칸 이름
  const P3_EXPECT = [
    ['fe_l', 'Fe 좌', '○'], ['fe_c', 'Fe 중', '○'], ['fe_r', 'Fe 우', '○'],
    ['sus_l', 'SUS 좌', '○'], ['sus_c', 'SUS 중', '○'], ['sus_r', 'SUS 우', '○'],
    ['product_only', '제품만', 'X'], ['product_fe', '제품+Fe', '○'], ['product_sus', '제품+SUS', '○'],
  ];
  const VALUE_TEXT = {
    'CCP-1P': (v) => `${num(v.gauss)}G · 청소 ${esc(v.rod_cleaned ?? '-')}`,
    'CCP-2B': (v) => `${esc(v.temp_c ?? '-')}℃ · ${fmtMinutes(v.dry_minutes)}`,
    'CCP-3P': (v) => {
      const off = P3_EXPECT.filter(([k, , want]) => v[k] !== want).map(([, label]) => label);
      return off.length ? `어긋남 ${esc(off.join('·'))}` : '9칸 정상';
    },
  };

  // 이탈 사유(B7): computed 판정 조건이면 "기준 …", 부적합 조건(nonconforming)의 gt·lt면 그 조건 자체
  function expectText(e) {
    if (!e) return '';
    if ('min' in e && 'max' in e) return `기준 ${num(e.min)}~${num(e.max)}`;
    if ('min' in e) return `기준 ${num(e.min)} 이상`;
    if ('max' in e) return `기준 ${num(e.max)} 이하`;
    if ('eq' in e) return `기준 ${esc(e.eq)}`;
    if ('in' in e) return `기준 ${esc([].concat(e.in).join('·'))}`;
    if ('gt' in e) return `${num(e.gt)} 초과`;
    if ('lt' in e) return `${num(e.lt)} 미만`;
    return '';
  }
  const reasonText = (r) => `${esc(r.label)} ${num(r.value)}${expectText(r.expect) ? ` <span class="te-hint">(${expectText(r.expect)})</span>` : ''}`;

  const staffList = (ids) => (ids || []).map((id) => `staff ${id}`).join('·');

  // ================================================= DSH-SC-02 개선조치 확인 창
  // row: {deviation_id, version, title, description, action_result, actor_id}. 결과 { ok } — 실패해도 토스트를 띄우고 부른 쪽이 다시 조회
  async function confirmCheck(row) {
    const body = `
      <div class="te-dsh-check">
        <p><b>${esc(row.title || '')}</b></p>
        <p>이탈: ${esc(row.description || '-')}</p>
        <p>조치: ${esc(row.action_result || '-')}${row.actor_id ? ` · staff ${esc(row.actor_id)}` : ''}</p>
        <p class="te-dsh-warn">확인하면 되돌릴 수 없습니다(확인 뒤 수정해도 확인 기록은 남습니다).</p>
      </div>`;
    const ok = await T.modal({
      title: '개선조치 확인', body,
      buttons: [{ label: '취소', value: false }, { label: '확인', value: true, cls: 'btn-primary te-dsh-check-ok' }],
    });
    if (!ok) return { ok: false, cancelled: true };
    const r = await api.post(`deviations/${row.deviation_id}/check`, { expected_version: row.version });
    if (r.ok) { T.toast('확인했습니다', 'success'); return { ok: true }; }
    const code = r.data && r.data.code;
    if (code === 'ALREADY_CHECKED') {
      const d = ((r.data.details || [])[0]) || {};
      T.toast(`이미 확인되었습니다(staff ${d.checked_by ?? '?'}, ${String(d.checked_at || '').slice(11, 16)})`, 'error');
    } else if (code === 'VERSION_CONFLICT') T.toast('다른 사용자가 먼저 처리했습니다', 'error');
    else if (code === 'NOT_CHECKER') T.toast('확인자로 지정되지 않았습니다', 'error');
    else if (code === 'DEVIATION_NOT_FOUND') T.toast('삭제된 개선조치입니다', 'error');
    else T.toast(T.errorText(r), 'error');
    return { ok: false, code };
  }

  // ================================================= DSH-SC-01 CCP 대시보드
  const Dash = {
    title: 'CCP 대시보드',
    root: null,
    date: '',
    mineOnly: false,
    showNoChecker: false,
    seq: 0,

    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      // 마지막 고른 날짜는 기억하지 않음(열 때마다 오늘 — S1b 3.1). 문서 상세에서 [뒤로]로 돌아올 때만 그 날짜
      this.date = (intent && intent.date) || seoulDay();
      this.mineOnly = false;
      this.showNoChecker = false;
      this.render();
    },

    render() {
      const max = seoulDay();
      this.root.innerHTML = `
        <div class="fade-in te-dsh">
          ${T.topBar('CCP 대시보드', '기준일 하루의 CCP 측정·한계기준 이탈·개선조치 확인 대기', null, { temp: false })}
          <div class="card te-dsh-head">
            <label class="te-user-label" for="dshDate">기준일</label>
            <input type="date" id="dshDate" class="form-control te-dsh-date" value="${esc(this.date)}" max="${max}">
            <span class="te-hint" id="dshDow">(${dow(this.date)})</span>
            <button class="btn btn-secondary btn-sm" id="dshRefresh">새로 고침</button>
            <span class="te-hint" id="dshAt"></span>
          </div>
          <div class="te-section"><div class="te-section-title">① CCP 현황</div><div id="dshCards" class="te-dsh-cards"><p class="te-hint">불러오는 중…</p></div></div>
          <div class="te-section"><div class="te-section-title">② 한계기준 이탈 <span id="dshDevCount" class="te-hint"></span></div><div id="dshDevs"><p class="te-hint">불러오는 중…</p></div></div>
          <div class="te-section" id="dshPendingWrap"><div id="dshPending"><p class="te-hint">불러오는 중…</p></div></div>
        </div>`;
      T.bindTopBar(this.root, () => this.render());
      const date = this.root.querySelector('#dshDate');
      date.addEventListener('change', () => {
        if (!date.value) { date.value = this.date; return; }
        if (date.value > seoulDay()) { T.toast('오늘 이후 날짜는 볼 수 없습니다.', 'error'); date.value = this.date; return; }
        this.date = date.value;
        this.root.querySelector('#dshDow').textContent = `(${dow(this.date)})`;
        this.load();
      });
      this.root.querySelector('#dshRefresh').addEventListener('click', () => { T.refreshBadges(); this.load(); });
      this.load();
    },

    load() {
      const seq = ++this.seq;
      this.root.querySelector('#dshAt').textContent = `마지막 조회 ${hhmm()}`;
      this.loadBoard(seq);
      this.loadPending(seq);
    },

    // ---------- ① 카드 · ② 이탈 (REQ-A09)
    async loadBoard(seq) {
      const r = await api.get(`ccp-dashboard?date=${this.date}`);
      if (seq !== this.seq || !this.root.isConnected) return;
      const cards = this.root.querySelector('#dshCards');
      const devs = this.root.querySelector('#dshDevs');
      if (!r.ok) {
        const fail = `<div class="te-dsh-fail">불러오지 못했습니다 <span class="te-hint">${esc(T.errorText(r))}</span> <button class="btn btn-secondary btn-sm" data-retry="board">다시</button></div>`;
        cards.innerHTML = fail;
        devs.innerHTML = '';
        this.root.querySelector('#dshDevCount').textContent = '';
        cards.querySelector('[data-retry]').addEventListener('click', () => this.loadBoard(this.seq));
        return;
      }
      const data = r.data;
      const isToday = data.base_date === seoulDay();
      const byType = Object.fromEntries(data.cards.map((c) => [c.type_code, c]));
      const order = CARD_ORDER.filter((t) => byType[t]).concat(data.cards.map((c) => c.type_code).filter((t) => !CARD_ORDER.includes(t)));
      cards.innerHTML = order.map((t) => this.cardHtml(byType[t], data.base_date, isToday)).join('');
      this.root.querySelector('#dshDevCount').textContent = `(${data.deviations.length})`;
      devs.innerHTML = data.deviations.length
        ? `<div class="te-table-wrap"><table class="data-table te-dsh-devs"><thead><tr><th>측정 시각</th><th>CCP</th><th>배치</th><th>어긋난 값</th><th>개선조치</th><th></th></tr></thead>
            <tbody>${data.deviations.map((x, i) => this.deviationHtml(x, i, data.base_date)).join('')}</tbody></table></div>`
        : '<p class="te-empty te-dsh-none">이탈 없음</p>';
      cards.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => this.openDoc(Number(b.dataset.open))));
      devs.querySelectorAll('[data-dev-open]').forEach((b) => b.addEventListener('click', () => {
        const x = data.deviations[Number(b.dataset.devOpen)];
        this.openDoc(x.document_id, x.deviation.state === 'none' ? { deviationNew: x.section_id } : { focus: 'deviation' });
      }));
    },

    cardHtml(c, base, isToday) {
      const n = c.counts;
      const head = `<div class="te-dsh-card-head">
          <div class="te-dsh-card-title">${esc(c.template_name)}</div>
          <div class="te-dsh-card-counts">배치 ${n.batches} · <span class="${n.todo ? 'te-dsh-warn' : ''}">작성 필요 ${n.todo}</span> · <span class="${n.deviation_rows ? 'te-judge-ng' : ''}">이탈 ${n.deviation_rows}</span></div>
        </div>`;
      if (!c.rows.length) {
        return `<div class="card te-dsh-card" data-card="${esc(c.type_code)}">${head}<p class="te-hint te-dsh-empty">이날 문서 없음 — 생산 배치가 없거나 아직 시작 전</p></div>`;
      }
      const rows = c.rows.map((x) => {
        const latest = x.latest;
        const verdict = latest && latest.verdict === '부적합' ? '<span class="te-judge-ng">⚠부적합</span>' : (latest && latest.verdict ? `<span class="te-judge-ok">${esc(latest.verdict)}</span>` : '');
        const fmt = VALUE_TEXT[c.type_code];
        const measure = x.no_rows
          ? '<div class="te-dsh-line te-dsh-warn">▲ 측정 없음</div>'
          : (latest
            ? `<div class="te-dsh-line">${esc(atText(latest.at, base))} ${esc(latest.phase || '')} · ${fmt ? fmt(latest.values || {}) : ''}${verdict ? ` · ${verdict}` : ''}</div>`
            : '<div class="te-dsh-line te-hint">측정 시각이 있는 행 없음</div>');
        const sub = [
          `측정 ${x.row_count}`,
          isToday && latest ? agoText(latest.at) : '',
          x.nonconforming_count ? `<span class="te-judge-ng">이탈 ${x.nonconforming_count}</span>` : '',
          `개선조치 ${x.deviation_count}`,
          x.detected_qty ? `<span class="te-judge-ng">검출 ${num(x.detected_qty)}</span>` : '',
        ].filter(Boolean).join(' · ');
        return `<div class="te-dsh-row${x.nonconforming_count || x.detected_qty ? ' te-dsh-row-ng' : ''}" data-doc="${x.document_id}">
            <div class="te-dsh-line"><b>${esc(x.label || `문서 #${x.document_id}`)}</b> ${esc(x.item_name || '')} ${T.statusBadge(x.status)}
              <button class="btn btn-secondary btn-sm te-dsh-open" data-open="${x.document_id}">열기</button></div>
            ${measure}
            <div class="te-dsh-line te-hint">${sub}</div>
          </div>`;
      }).join('');
      return `<div class="card te-dsh-card" data-card="${esc(c.type_code)}">${head}${rows}</div>`;
    },

    deviationHtml(x, i, base) {
      const at = x.at ? esc(atText(x.at, base)) : `<span class="te-hint">${x.section_def === 'summary' ? '요약' : '시각 없음'}</span>`;
      const d = x.deviation || { state: 'none' };
      const state = {
        none: '<span class="te-judge-ng">⚠ 개선조치 없음</span>',
        pending: `<span class="te-dsh-warn">확인 대기</span> <span class="te-hint">${esc(staffList(d.checker_ids))}</span>`,
        checked: `<span class="te-judge-ok">확인됨</span> staff ${esc(d.checked_by)} ${esc(String(d.checked_at || '').slice(11, 16))}`,
        no_checker: '<span class="te-hint">확인자 없음</span>',
      }[d.state] || esc(d.state);
      return `<tr class="${d.state === 'none' ? 'te-row-ng' : ''}" data-dev-state="${esc(d.state)}">
          <td class="te-nowrap">${at}</td><td>${esc(x.type_code)}</td><td>${esc(x.label || '')}</td>
          <td>${(x.reasons || []).map(reasonText).join('<br>') || '-'}</td><td>${state}</td>
          <td><button class="btn btn-secondary btn-sm" data-dev-open="${i}">열기</button></td></tr>`;
    },

    // ---------- ③ 개선조치 확인 대기 (DOC-A22)
    async loadPending(seq) {
      const r = await api.get(`deviations/pending?date=${this.date}`);
      if (seq !== this.seq || !this.root.isConnected) return;
      const box = this.root.querySelector('#dshPending');
      if (!r.ok) {
        box.innerHTML = `<div class="te-section-title">③ 개선조치 확인 대기</div>
          <div class="te-dsh-fail">불러오지 못했습니다 <span class="te-hint">${esc(T.errorText(r))}</span> <button class="btn btn-secondary btn-sm" data-retry="pending">다시</button></div>`;
        box.querySelector('[data-retry]').addEventListener('click', () => this.loadPending(this.seq));
        return;
      }
      this.pending = r.data;
      this.renderPending();
    },

    renderPending() {
      const box = this.root.querySelector('#dshPending');
      const p = this.pending;
      const me = !!api.staffId && 'mine' in p.counts;
      const rows = this.mineOnly && me ? p.rows.filter((x) => x.can_check) : p.rows;
      const head = `<div class="te-section-head te-dsh-pending-head">
          <span class="te-section-title">③ 개선조치 확인 대기 (${p.counts.total})${me ? ` · 내 확인 대기 ${p.counts.mine}` : ''}</span>
          <span class="te-dsh-tools">
            ${me ? `<label class="te-check"><input type="checkbox" id="dshMine" ${this.mineOnly ? 'checked' : ''}> 내 확인 대기만</label>` : ''}
            ${p.no_checker.count ? `<a href="#" id="dshNoChecker" class="te-hint">확인자 없음 ${p.no_checker.count}건 ${this.showNoChecker ? '▾' : '▸'}</a>` : ''}
          </span></div>`;
      const line = (x, i, list) => `<tr data-pending="${x.deviation_id}">
          <td class="te-nowrap">${esc(md(x.work_date))}</td>
          <td>${esc(x.type_code)} ${esc(x.target_summary || '')}</td>
          <td>${esc(x.description || '')}</td>
          <td title="${esc(x.action_result || '')}">${esc(this.cut(x.action_result || '-', 40))}</td>
          <td>${x.actor_id ? `staff ${esc(x.actor_id)}` : '-'}</td>
          <td>${x.checker_ids.length ? `확인자 ${esc(staffList(x.checker_ids))}` : '<span class="te-hint">확인자 없음</span>'}</td>
          <td class="te-nowrap te-hint">${esc(agoText(x.created_at))}</td>
          <td class="te-nowrap">${list === 'rows' && x.can_check && api.staffId ? `<button class="btn btn-primary btn-sm" data-check="${i}">확인</button>` : '<span class="te-hint">–</span>'}
            <button class="btn btn-secondary btn-sm" data-popen="${x.document_id}">열기</button></td></tr>`;
      const table = (list, key) => `<div class="te-table-wrap"><table class="data-table te-dsh-pending"><thead><tr><th>작업일</th><th>양식·대상</th><th>이탈내용</th><th>개선조치 및 결과</th><th>조치자</th><th>확인자</th><th>쓴 지</th><th></th></tr></thead>
          <tbody>${list.map((x, i) => line(x, i, key)).join('')}</tbody></table></div>`;
      const body = rows.length ? table(rows, 'rows') : '<p class="te-empty">확인할 개선조치가 없습니다.</p>';
      const noChecker = this.showNoChecker && p.no_checker.count
        ? `<div class="te-dsh-nochecker"><div class="te-hint">확인자 없는 개선조치 — 확인 대상이 아닙니다. 문서 상세에서 확인자를 지정할 수 있습니다.</div>${table(p.no_checker.rows, 'no_checker')}</div>` : '';
      box.innerHTML = head + body + noChecker + this.otherDaysHtml(p);
      box.querySelector('#dshMine')?.addEventListener('change', (e) => { this.mineOnly = e.target.checked; this.renderPending(); });
      box.querySelector('#dshNoChecker')?.addEventListener('click', (e) => { e.preventDefault(); this.showNoChecker = !this.showNoChecker; this.renderPending(); });
      box.querySelectorAll('[data-check]').forEach((b) => b.addEventListener('click', async () => {
        const x = rows[Number(b.dataset.check)];
        const result = await confirmCheck({
          deviation_id: x.deviation_id, version: x.version, title: `${x.type_code} ${x.target_summary || ''} (${md(x.work_date)})`,
          description: x.description, action_result: x.action_result, actor_id: x.actor_id,
        });
        if (!result.cancelled) this.load();
      }));
      box.querySelectorAll('[data-popen]').forEach((b) => b.addEventListener('click', () => this.openDoc(Number(b.dataset.popen), { focus: 'deviation' })));
      box.querySelectorAll('[data-other-day]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        this.date = a.dataset.otherDay;
        this.render();
      }));
      box.querySelectorAll('[data-other-doc]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        this.openDoc(Number(a.dataset.otherDoc), { focus: 'deviation' });
      }));
    },

    // 다른 날 내 확인 대기(S1b 3.4): 과거 날짜는 기준일 바꾸기, 미래 작업일은 문서 [열기], 10개 날짜 넘으면 "외 n건"
    otherDaysHtml(p) {
      const days = p.other_days_mine || [];
      if (!days.length) return '';
      const shown = days.reduce((a, d) => a + d.count, 0);
      const rest = (p.other_days_mine_total || 0) - shown;
      const parts = days.map((d) => (d.future
        ? `${esc(md(d.work_date))} (${d.count}) ${(d.document_ids || []).map((id) => `<a href="#" data-other-doc="${id}">문서 #${id} 열기</a>`).join(' ')}`
        : `<a href="#" data-other-day="${esc(d.work_date)}">${esc(md(d.work_date))} (${d.count})</a>`));
      return `<div class="te-dsh-other" id="dshOther">▸ 다른 날 내 확인 대기 ${p.other_days_mine_total}건 — ${parts.join(' · ')}${rest > 0 ? ` · 외 ${rest}건` : ''}</div>`;
    },

    cut(text, n) { return text.length > n ? `${text.slice(0, n)}…` : text; },

    openDoc(documentId, extra = {}) {
      T.open('doc-box', { documentId, back: { page: 'ccp-dashboard', intent: { date: this.date } }, ...extra });
    },
  };

  window.TempEntryDashboard = { confirmCheck };
  T.register('ccp-dashboard', Dash);
})();
