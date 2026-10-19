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
  // D-171 생산 상태(수불 배치 status): 정렬 순서와 배지
  const PROD_RANK = { IN_PROGRESS: 0, PLANNED: 1, COMPLETED: 2 };
  const PROD_LABEL = { IN_PROGRESS: ['생산중', 'te-b-green'], PLANNED: ['생산 전', 'te-b-grey'], COMPLETED: ['생산 종료', 'te-b-blue'], CANCELLED: ['생산 취소', 'te-b-grey'] };
  // 공정 카드 이름: "CCP-1P 모니터링일지(쇳가루 제거)" → "CCP-1P 쇳가루 제거"(공정 순서는 서버 cards 순서 = 1P·2B·3P)
  const procName = (name, code) => {
    const m = /\(([^)]+)\)\s*$/.exec(name || '');
    return m ? `${code} ${m[1]}` : (name || code);
  };

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
    T.refreshBadges();  // ISS-047: 실패(그사이 다른 처리)도 사이드바 숫자를 다시 셈 — 배지는 성공한 쓰기 뒤에만 자동으로 셈
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
    board: null,
    pending: null,
    opened: {},       // 배치 영역 펼침(사용자가 직접 바꾼 것만 — 이 화면을 연 동안)
    panelOpened: {},  // 이탈·개선조치 칸 펼침
    notesClosed: {},  // 특이사항 칸 접음(기본 펼침)

    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      // 마지막 고른 날짜는 기억하지 않음(열 때마다 오늘 — S1b 3.1). 문서 상세에서 [뒤로]로 돌아올 때만 그 날짜
      this.date = (intent && intent.date) || seoulDay();
      this.mineOnly = false;
      this.showNoChecker = false;
      this.opened = {};
      this.panelOpened = {};
      this.notesClosed = {};
      // P11 S5 r2: 생산 화면 [CCP 대시보드에서 보기]로 들어오면 그 배치 영역을 펼쳐서 보여 줌
      this.focus = (intent && intent.focusBatch) || null;
      if (this.focus) this.opened[this.focus] = true;
      this.board = null;
      this.pending = null;
      this.render();
    },

    render() {
      const max = seoulDay();
      this.root.innerHTML = `
        <div class="fade-in te-dsh">
          ${T.topBar('CCP 대시보드', '기준일 하루의 CCP 측정을 생산 배치별로 — 이탈·개선조치·특이사항, 개선조치 확인 대기', null, { temp: false })}
          <div class="card te-dsh-head">
            <label class="te-user-label" for="dshDate">기준일</label>
            <input type="date" id="dshDate" class="form-control te-dsh-date" value="${esc(this.date)}" max="${max}">
            <span class="te-hint" id="dshDow">(${dow(this.date)})</span>
            <button class="btn btn-secondary btn-sm" id="dshRefresh">새로 고침</button>
            <span class="te-hint" id="dshAt"></span>
          </div>
          <div class="te-section"><div class="te-section-title">① CCP 현황</div><div id="dshCards"><p class="te-hint">불러오는 중…</p></div></div>
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
      this.board = null;
      this.pending = null;
      this.loadBoard(seq);
      this.loadPending(seq);
    },

    // ---------- ① CCP 현황 — 배치 영역 (REQ-A09, P11 S5 r1 — p11-s5-r1-lines.md v8, 사용설명서 1.5)
    // 서버 응답(공정별 cards)을 배치(label = 배치번호)로 다시 묶는다. 영역 이름 = 품목명(배치번호)
    async loadBoard(seq) {
      const r = await api.get(`ccp-dashboard?date=${this.date}`);
      if (seq !== this.seq || !this.root.isConnected) return;
      const cards = this.root.querySelector('#dshCards');
      if (!r.ok) {
        this.board = null;
        cards.innerHTML = `<div class="te-dsh-fail">불러오지 못했습니다 <span class="te-hint">${esc(T.errorText(r))}</span> <button class="btn btn-secondary btn-sm" data-retry="board">다시</button></div>`;
        cards.querySelector('[data-retry]').addEventListener('click', () => this.loadBoard(this.seq));
        return;
      }
      this.board = this.groupBatches(r.data);
      this.renderBoard();
      if (this.pending) this.renderPending();  // 확인 대기 대상 이름(품목명(배치번호))
    },

    groupBatches(data) {
      const procs = data.cards.map((c) => ({ type_code: c.type_code, name: procName(c.template_name, c.type_code) }));
      const byLabel = new Map();
      const docs = {};
      const batch = (label) => {
        if (!byLabel.has(label)) byLabel.set(label, { label, item: '', docs: {}, devs: [], notes: [] });
        return byLabel.get(label);
      };
      data.cards.forEach((c) => c.rows.forEach((row) => {
        const b = batch(row.label || `문서 #${row.document_id}`);
        b.docs[c.type_code] = row;
        if (!b.item && row.item_name) b.item = row.item_name;
        docs[row.document_id] = { batch: b, type_code: c.type_code, row };
      }));
      const of = (x) => (docs[x.document_id] ? docs[x.document_id].batch : batch(x.label || `문서 #${x.document_id}`));
      data.deviations.forEach((x) => of(x).devs.push({ ...x, kind: 'row' }));
      (data.other_deviations || []).forEach((x) => of(x).devs.push({ ...x, kind: 'other' }));
      (data.notes || []).forEach((x) => of(x).notes.push(x));
      const list = [...byLabel.values()].map((b) => {
        const rows = Object.values(b.docs);
        const state = (x) => (x.deviation || {}).state;
        b.counts = {
          deviation_rows: rows.reduce((a, x) => a + x.nonconforming_count, 0),
          no_action: b.devs.filter((x) => x.kind === 'row' && state(x) === 'none').length,
          pending: b.devs.filter((x) => state(x) === 'pending').length,
          no_rows: rows.filter((x) => x.no_rows).length,
          todo: rows.filter((x) => x.todo).length,
          notes: b.notes.length,
        };
        const c = b.counts;
        b.rank = c.no_action ? 0 : c.pending ? 1 : c.no_rows ? 2 : c.todo ? 3 : 4;
        b.title = b.item ? `${b.item}(${b.label})` : b.label;
        b.latest = rows.map((x) => (x.latest && x.latest.at) || '').sort().pop() || '';
        b.devs.sort((x, y) => (x.kind === y.kind ? 0 : x.kind === 'row' ? -1 : 1));
        return b;
      });
      // 배치마다 적용 CCP 공정과 순서(서버 batches[].processes — 품목별 규칙). 규칙에 없는 문서는 뒤에
      const orderOf = Object.fromEntries((data.batches || []).map((x) => [x.label, x.processes || []]));
      const procByCode = Object.fromEntries(procs.map((p) => [p.type_code, p]));
      list.forEach((b) => {
        const rule = (orderOf[b.label] || []).filter((code) => b.docs[code] || procByCode[code]);
        const extra = procs.map((p) => p.type_code).filter((code) => b.docs[code] && !rule.includes(code));
        b.order = [...rule, ...extra].map((code) => procByCode[code] || { type_code: code, name: code });
      });
      // D-171 정렬: 생산중 → 생산 전 → 생산 종료(→ 그 밖), 같으면 생산 시작 일시 빠른 순(없으면 뒤), 품목명·배치번호
      const infoOf = Object.fromEntries((data.batches || []).map((x) => [x.label, x]));
      list.forEach((b) => {
        const info = infoOf[b.label] || {};
        b.prod = info.status || null;
        b.qty = { planned: info.planned_qty, output: info.output_qty, unit: info.unit || '' };
        b.startedAt = info.started_at || '';
        b.batchId = info.batch_id || null;  // P11 S5 r2: [생산 기록] 링크
        b.prodRank = PROD_RANK[b.prod] ?? 3;
      });
      list.sort((a, b) => a.prodRank - b.prodRank
        || (a.startedAt ? 0 : 1) - (b.startedAt ? 0 : 1) || a.startedAt.localeCompare(b.startedAt)
        || a.item.localeCompare(b.item, 'ko') || a.label.localeCompare(b.label));
      const total = { batches: list.length };
      ['deviation_rows', 'no_action', 'pending', 'no_rows', 'todo', 'notes'].forEach((k) => { total[k] = list.reduce((a, b) => a + b.counts[k], 0); });
      return { base: data.base_date, isToday: data.base_date === seoulDay(), procs, list, total, docs };
    },

    // 배지(사용설명서 1.5.2). 0이면 안 그림
    badges(c, { short = false } = {}) {
      const items = [
        [c.deviation_rows, 'te-b-red', `⚠ 이탈 ${c.deviation_rows}`],
        [c.no_action, 'te-b-red', `⚠ 개선조치 없음 ${c.no_action}`],
        [c.pending, 'te-b-orange', `● 확인 대기 ${c.pending}`],
        [c.no_rows, 'te-b-orange', `▲ 측정 없음 ${c.no_rows}`],
        [c.todo, 'te-b-grey', `작성 필요 ${c.todo}`],
        [c.notes, 'te-b-blue', `✎ 특이사항 ${c.notes}`],
      ];
      const shown = items.filter(([n]) => n).filter(([, cls]) => !short || cls !== 'te-b-grey');
      return shown.map(([, cls, text]) => `<span class="te-b ${cls}">${esc(text)}</span>`).join('');
    },

    renderBoard() {
      const box = this.root.querySelector('#dshCards');
      const B = this.board;
      if (!B.list.length) {
        box.innerHTML = '<div class="card te-dsh-total"><b>전체</b> <span class="te-hint">이날 생산 배치 없음</span></div>';
        return;
      }
      const t = B.total;
      const all = this.badges(t);
      box.innerHTML = `
        <div class="card te-dsh-total" id="dshTotal">
          <b>전체</b> <span class="te-hint">배치 ${t.batches}</span>
          <span id="dshTotalBadges">${all || '<span class="te-b te-b-green">이상 없음</span>'}</span>
          <span class="te-dsh-grow"></span>
          <button class="btn btn-secondary btn-sm" id="dshOpenAll">모두 펼치기</button>
          <button class="btn btn-secondary btn-sm" id="dshCloseAll">모두 접기</button>
        </div>
        ${B.list.map((b) => (this.isOpen(b) ? this.areaHtml(b) : this.foldHtml(b))).join('')}`;
      box.querySelector('#dshOpenAll').addEventListener('click', () => { B.list.forEach((b) => { this.opened[b.label] = true; }); this.renderBoard(); });
      box.querySelector('#dshCloseAll').addEventListener('click', () => { B.list.forEach((b) => { this.opened[b.label] = false; }); this.renderBoard(); });
      box.querySelectorAll('[data-toggle]').forEach((el) => el.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const label = el.dataset.toggle;
        const b = B.list.find((x) => x.label === label);
        this.opened[label] = !this.isOpen(b);
        this.renderBoard();
      }));
      box.querySelectorAll('[data-prod-batch]').forEach((el) => el.addEventListener('click', () => T.productionPage().openBatch(Number(el.dataset.prodBatch), 'work')));
      if (this.focus) {  // 생산 화면에서 들어온 배치: 그 영역으로 스크롤·잠깐 강조(한 번만)
        const el = [...box.querySelectorAll('.te-dsh-area')].find((x) => x.dataset.batch === this.focus);
        if (el) { el.classList.add('te-dsh-focus'); el.scrollIntoView({ block: 'center' }); }
        this.focus = null;
      }
      box.querySelectorAll('[data-panel]').forEach((el) => el.addEventListener('click', () => {
        const label = el.dataset.panel;
        const b = B.list.find((x) => x.label === label);
        this.panelOpened[label] = !this.isPanelOpen(b);
        this.renderBoard();
      }));
      box.querySelectorAll('[data-notes]').forEach((el) => el.addEventListener('click', () => {
        const label = el.dataset.notes;
        this.notesClosed[label] = !this.notesClosed[label];
        this.renderBoard();
      }));
      box.querySelectorAll('[data-open]').forEach((el) => el.addEventListener('click', () => this.openDoc(Number(el.dataset.open))));
      box.querySelectorAll('[data-dev-new]').forEach((el) => el.addEventListener('click', () => this.openDoc(Number(el.dataset.devDoc), { deviationNew: Number(el.dataset.devNew) })));
      box.querySelectorAll('[data-dev-open]').forEach((el) => el.addEventListener('click', () => this.openDoc(Number(el.dataset.devOpen), { focus: 'deviation' })));
      box.querySelectorAll('[data-area-check]').forEach((el) => el.addEventListener('click', async () => {
        const [label, i] = el.dataset.areaCheck.split('|');
        const b = B.list.find((x) => x.label === label);
        const x = b.devs[Number(i)];
        const dv = x.deviation;
        const result = await confirmCheck({
          deviation_id: dv.deviation_id, version: dv.version,
          title: `${x.type_code} ${b.title} · ${x.type_code.replace('CCP-', '')} (${md(B.base)})`,
          description: dv.description, action_result: dv.action_result, actor_id: dv.actor_id,
        });
        if (!result.cancelled) this.load();
      }));
    },

    // 처음 모양(사용설명서 1.5.3): 개선조치 없음·확인 대기가 있으면 펼침. 직접 바꾼 것은 이 화면을 연 동안 유지
    isOpen(b) { return b.label in this.opened ? this.opened[b.label] : !!(b.counts.no_action || b.counts.pending); },
    isPanelOpen(b) { return b.label in this.panelOpened ? this.panelOpened[b.label] : !!(b.counts.no_action || b.counts.pending); },

    // 배치 요약 줄의 내용(접힘·펼침 머리 공통): 이름 · 공정 결과(그 배치의 공정 순서, 결과마다 공정 이름) · 이탈·개선조치·특이사항 · 최근 측정
    // 열 이름 줄은 없음(품목마다 공정이 달라 고정 열이 맞지 않음 — 사용자, D-168)
    rowCells(b) {
      const B = this.board;
      const chip = (p) => {
        const row = b.docs[p.type_code];
        let mark;
        if (!row) mark = '<span class="te-hint">문서 없음</span>';
        else if (row.nonconforming_count) mark = `<span class="te-judge-ng">⚠ 이탈 ${row.nonconforming_count}</span>`;
        else if (row.no_rows) mark = '<span class="te-dsh-warn">▲ 측정 없음</span>';
        else if (row.latest && row.latest.verdict === '적합') mark = '<span class="te-judge-ok">✓ 적합</span>';
        else mark = '<span class="te-hint">측정 시각 없음</span>';
        return `<span class="te-dsh-chip" data-fold-proc="${esc(p.type_code)}"><b>${esc(p.name)}</b> ${mark}${row ? ` ${T.statusBadge(row.status)}` : ''}</span>`;
      };
      const c = b.counts;
      const dev = [c.no_action ? `<span class="te-b te-b-red">⚠ 개선조치 없음 ${c.no_action}</span>` : '',
        c.pending ? `<span class="te-b te-b-orange">● 확인 대기 ${c.pending}</span>` : '',
        c.notes ? `<span class="te-b te-b-blue">✎ ${c.notes}</span>` : ''].join('');
      const last = b.latest ? `<span class="te-hint" title="최근 측정">최근 ${esc(atText(b.latest, B.base))}</span>` : '';
      const prod = PROD_LABEL[b.prod];
      // D-172: 이름 옆 생산 정보 — 생산 수량(계획, 산출이 있으면 산출도)·생산 시작 시각
      const q = b.qty || {};
      const unit = q.unit ? ` ${esc(q.unit)}` : '';
      const facts = [
        typeof q.planned === 'number' ? `계획 ${num(q.planned)}${unit}` : '',
        typeof q.output === 'number' && q.output > 0 ? `산출 ${num(q.output)}${unit}` : '',
        b.startedAt ? `시작 ${esc(atText(String(b.startedAt).replace(' ', 'T'), B.base))}` : (b.prod === 'PLANNED' ? '시작 전' : ''),
      ].filter(Boolean);
      const info = facts.length ? `<span class="te-dsh-prodinfo" data-prodinfo>${facts.join(' · ')}</span>` : '';
      return `<span class="te-dsh-namebox"><b class="te-dsh-name">${esc(b.title)}</b>${prod ? `<span class="te-b ${prod[1]}" data-prod="${esc(b.prod)}">${prod[0]}</span>` : ''}${info}</span>
          <span class="te-dsh-flow">${b.order.map(chip).join('<span class="te-dsh-arrow">→</span>')}</span>
          <span class="te-dsh-devsum">${dev}</span>${last}`;
    },

    // 배치 요약 줄(접힌 배치 영역)
    foldHtml(b) {
      return `<div class="card te-dsh-row te-dsh-fold" data-toggle="${esc(b.label)}" data-batch="${esc(b.label)}" title="눌러서 펼치기">
          <span class="te-dsh-caret">▸</span>${this.rowCells(b)}</div>`;
    },

    // 펼친 배치 영역: 머리(배치 요약 줄과 같은 내용) · 영역 배지 · 공정 카드(그 배치의 공정 순서) · 이탈·개선조치 칸
    areaHtml(b) {
      const cards = b.order.map((p) => this.procCardHtml(b, p)).join('');
      return `<div class="card te-dsh-area" data-batch="${esc(b.label)}">
          <div class="te-dsh-row te-dsh-area-head" data-toggle="${esc(b.label)}" title="눌러서 접기"><span class="te-dsh-caret">▾</span>${this.rowCells(b)}</div>
          <div class="te-dsh-area-badges">${this.badges(b.counts) || '<span class="te-b te-b-green">이상 없음</span>'}${b.batchId && T.productionPage() ? `<button class="btn btn-secondary btn-sm te-dsh-prodlink" data-prod-batch="${b.batchId}" title="생산지시·실적의 이 배치">생산 기록 ↗</button>` : ''}</div>
          <div class="te-dsh-procs">${cards}</div>
          ${this.panelHtml(b)}
          ${this.notesHtml(b)}
        </div>`;
    },

    procCardHtml(b, p) {
      const B = this.board;
      const row = b.docs[p.type_code];
      if (!row) return `<div class="te-dsh-proc"><div class="te-dsh-proc-head">${esc(p.name)}</div><p class="te-hint">문서 없음</p></div>`;
      const latest = row.latest;
      const notes = b.notes.filter((n) => n.document_id === row.document_id);
      const pen = notes.length ? ` <span class="te-b te-b-blue" title="${esc(notes.map((n) => `${n.field_label}: ${n.text}`).join('\n'))}">✎</span>` : '';
      const verdict = latest && latest.verdict === '부적합' ? '<span class="te-judge-ng">⚠부적합</span>' : (latest && latest.verdict ? `<span class="te-judge-ok">${esc(latest.verdict)}</span>` : '');
      const fmt = VALUE_TEXT[p.type_code];
      const measure = row.no_rows
        ? '<div class="te-dsh-line te-dsh-warn">▲ 측정 없음</div>'
        : (latest
          ? `<div class="te-dsh-line">${esc(atText(latest.at, B.base))} ${esc(latest.phase || '')} · ${fmt ? fmt(latest.values || {}) : ''}${verdict ? ` · ${verdict}` : ''}${pen}</div>`
          : `<div class="te-dsh-line te-hint">측정 시각이 있는 행 없음${pen}</div>`);
      const sub = [
        `측정 ${row.row_count}`,
        B.isToday && latest ? agoText(latest.at) : '',
        row.nonconforming_count ? `<span class="te-judge-ng">이탈 ${row.nonconforming_count}</span>` : '',
        `개선조치 ${row.deviation_count}`,
        row.detected_qty ? `<span class="te-judge-ng">검출 ${num(row.detected_qty)}</span>` : '',
      ].filter(Boolean).join(' · ');
      const probs = [row.nonconforming_count ? `<span class="te-b te-b-red">⚠ 이탈 ${row.nonconforming_count}</span>` : '',
        row.no_rows ? '<span class="te-b te-b-orange">▲ 측정 없음</span>' : ''].join('');
      return `<div class="te-dsh-proc${row.nonconforming_count || row.detected_qty ? ' te-dsh-proc-ng' : ''}" data-doc="${row.document_id}" data-proc="${esc(p.type_code)}">
          <div class="te-dsh-proc-head">${esc(p.name)} ${T.statusBadge(row.status)}${probs}
            <button class="btn btn-secondary btn-sm te-dsh-open" data-open="${row.document_id}">열기</button></div>
          ${measure}
          <div class="te-dsh-line te-hint">${sub}</div>
        </div>`;
    },

    // 이탈·개선조치 칸(사용설명서 1.5.4·1.5.5): 이탈 표 + 특이사항 표. 품목·배치 열 없음(영역 안은 같은 배치)
    panelHtml(b) {
      // D-170: 펼친 배치 영역에는 늘 둠 — 비면 "이탈·개선조치 없음" 한 줄(특이사항은 따로 칸 notesHtml — D-169)
      if (!b.devs.length) return `<div class="te-dsh-panel te-dsh-panel-empty" data-panel-box="${esc(b.label)}"><div class="te-dsh-panel-head te-dsh-empty-head">이탈·개선조치 없음</div></div>`;
      const B = this.board;
      const open = this.isPanelOpen(b);
      const c = b.counts;
      const checked = b.devs.filter((x) => (x.deviation || {}).state === 'checked').length;
      const title = `이탈·개선조치 ${b.devs.length}`;
      const head = `<div class="te-dsh-panel-head" data-panel="${esc(b.label)}">${open ? '▾' : '▸'} ${title}
          ${c.no_action ? `<span class="te-b te-b-red">⚠ 개선조치 없음 ${c.no_action}</span>` : ''}${c.pending ? `<span class="te-b te-b-orange">● 확인 대기 ${c.pending}</span>` : ''}${checked ? `<span class="te-b te-b-grey">확인됨 ${checked}</span>` : ''}</div>`;
      if (!open) return `<div class="te-dsh-panel te-dsh-panel-closed" data-panel-box="${esc(b.label)}">${head}</div>`;
      const me = Number(api.staffId);
      const devRow = (x, i) => {
        const dv = x.deviation || { state: 'none' };
        const proc = x.type_code.replace('CCP-', '');
        const at = x.kind === 'row'
          ? (x.at ? esc(atText(x.at, B.base)) : `<span class="te-hint">${x.section_def === 'summary' ? '요약' : '시각 없음'}</span>`)
          : '<span class="te-hint">–</span>';
        const what = x.kind === 'row'
          ? ((x.reasons || []).map(reasonText).join('<br>') || '-')
          : `<span class="te-hint">${x.section_id ? '관련 행 적합' : '행 지정 없음'}</span>`;
        const action = dv.state === 'none' ? '<span class="te-hint">–</span>'
          : `<span title="${esc(dv.action_result || '')}">${esc(this.cut(dv.action_result || dv.description || '-', 40))}</span>${dv.actor_id ? ` <span class="te-hint">· staff ${esc(dv.actor_id)}</span>` : ''}`;
        const state = {
          none: '<span class="te-judge-ng">⚠ 개선조치 없음</span>',
          pending: `<span class="te-dsh-warn">● 확인 대기</span> <span class="te-hint">${esc(staffList(dv.checker_ids))}</span>`,
          checked: `<span class="te-judge-ok">확인됨</span> staff ${esc(dv.checked_by)} ${esc(String(dv.checked_at || '').slice(11, 16))}`,
          no_checker: '<span class="te-hint">확인자 없음</span>',
        }[dv.state] || esc(dv.state);
        const btns = [
          dv.state === 'pending' && me && (dv.checker_ids || []).includes(me) ? `<button class="btn btn-primary btn-sm" data-area-check="${esc(b.label)}|${i}">확인</button>` : '',
          dv.state === 'none' ? `<button class="btn btn-secondary btn-sm" data-dev-new="${x.section_id}" data-dev-doc="${x.document_id}">개선조치 쓰기</button>` : '',
          dv.state !== 'none' ? `<button class="btn btn-secondary btn-sm" data-dev-open="${x.document_id}">열기</button>` : '',
        ].join(' ');
        return `<tr class="${dv.state === 'none' ? 'te-row-ng' : ''}" data-dev-state="${esc(dv.state)}" data-dev-kind="${x.kind}"><td class="te-nowrap">${at}</td><td>${esc(proc)}</td><td>${what}</td><td>${action}</td><td>${state}</td><td class="te-nowrap">${btns}</td></tr>`;
      };
      const devTable = b.devs.length
        ? `<table class="data-table te-dsh-devtable"><thead><tr><th>시각</th><th>공정</th><th>어긋난 값</th><th>개선조치</th><th>상태</th><th></th></tr></thead><tbody>${b.devs.map(devRow).join('')}</tbody></table>` : '';
      return `<div class="te-dsh-panel" data-panel-box="${esc(b.label)}">${head}<div class="te-table-wrap">${devTable}</div></div>`;
    },

    // 특이사항 칸(D-169 — 이탈·개선조치 칸과 따로, 이탈이 없어도 있으면 늘 펼친 채). 머리를 누르면 접을 수 있음
    notesHtml(b) {
      // D-170: 늘 둠 — 비면 "특이사항 없음" 한 줄
      if (!b.notes.length) return `<div class="te-dsh-notes te-dsh-notes-empty" data-notes-box="${esc(b.label)}"><div class="te-dsh-notes-head te-dsh-empty-head">✎ 특이사항 없음</div></div>`;
      const B = this.board;
      const open = !(b.label in this.notesClosed) || !this.notesClosed[b.label];
      const head = `<div class="te-dsh-notes-head" data-notes="${esc(b.label)}">${open ? '▾' : '▸'} ✎ 특이사항 ${b.notes.length}</div>`;
      if (!open) return `<div class="te-dsh-notes te-dsh-notes-closed" data-notes-box="${esc(b.label)}">${head}</div>`;
      const rows = b.notes.map((n) => `<tr data-note="${n.section_id}">
          <td class="te-nowrap">${n.at ? esc(atText(n.at, B.base)) : '<span class="te-hint">요약</span>'}</td><td>${esc(n.type_code.replace('CCP-', ''))}</td><td>${esc(n.text)}</td>
          <td class="te-hint">${esc(n.section_label)} ${esc(n.field_label)}</td><td><button class="btn btn-secondary btn-sm" data-open="${n.document_id}">열기</button></td></tr>`).join('');
      return `<div class="te-dsh-notes" data-notes-box="${esc(b.label)}">${head}<div class="te-table-wrap"><table class="data-table te-dsh-notetable"><thead><tr><th>시각</th><th>공정</th><th>내용</th><th>칸</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
    },

    // ---------- ② 개선조치 확인 대기 (DOC-A22) — S5 r1에서 ② 이탈 목록을 배치 영역으로 옮겨 번호만 바뀜
    async loadPending(seq) {
      const r = await api.get(`deviations/pending?date=${this.date}`);
      if (seq !== this.seq || !this.root.isConnected) return;
      const box = this.root.querySelector('#dshPending');
      if (!r.ok) {
        box.innerHTML = `<div class="te-section-title">② 개선조치 확인 대기</div>
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
          <span class="te-section-title">② 개선조치 확인 대기 (${p.counts.total})${me ? ` · 내 확인 대기 ${p.counts.mine}` : ''}</span>
          <span class="te-dsh-tools">
            ${me ? `<label class="te-check"><input type="checkbox" id="dshMine" ${this.mineOnly ? 'checked' : ''}> 내 확인 대기만</label>` : ''}
            ${p.no_checker.count ? `<a href="#" id="dshNoChecker" class="te-hint">확인자 없음 ${p.no_checker.count}건 ${this.showNoChecker ? '▾' : '▸'}</a>` : ''}
          </span></div>`;
      const line = (x, i, list) => `<tr data-pending="${x.deviation_id}">
          <td class="te-nowrap">${esc(md(x.work_date))}</td>
          <td>${esc(x.type_code)} ${esc(this.targetText(x))}</td>
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
          deviation_id: x.deviation_id, version: x.version, title: `${x.type_code} ${this.targetText(x)} (${md(x.work_date)})`,
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

    // CCP 줄 대상 = 품목명(배치번호) · 공정(S5 r1 — 대시보드만, 서버 target_summary는 그대로). 현황을 못 읽었으면 서버 표시
    targetText(x) {
      const hit = this.board && this.board.docs[x.document_id];
      if (!hit) return x.target_summary || '';
      return `${hit.batch.title} · ${hit.type_code.replace('CCP-', '')}`;
    },

    cut(text, n) { return text.length > n ? `${text.slice(0, n)}…` : text; },

    openDoc(documentId, extra = {}) {
      T.open('doc-box', { documentId, back: { page: 'ccp-dashboard', intent: { date: this.date } }, ...extra });
    },
  };

  window.TempEntryDashboard = { confirmCheck };
  T.register('ccp-dashboard', Dash);
})();
