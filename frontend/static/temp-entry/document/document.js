// =============================================
// 개발 검증 › 문서 작성 (P1 DOC 사용 화면 + P4 확장)
// 화면: DOC-SC-01 목록 · 02 양식 선택 · 03 작성/수정 폼 · 04 상세(+ P3 결재 영역) · 05 삭제 확인
//       P4: 09 작성완료 확인·검사 결과, 이탈·개선조치 영역, 작성 요구 문서 표시
//       P6: 정정 시작(WF-SC-08)·정정 배너·정정 취소(WF-SC-10), D03 작성완료의 판정 전달(DOC-SC-09)
//       P7: 목록 묶음 줄(DOC-SC-01)·육안검사 묶음 상세(DOC-SC-10)·점검자 일괄 지정(DOC-SC-11)·최종판정 강조(DOC-SC-03·04)
//           — dev-notes/document-workflow/p7-s1-screens.md 3장, API p7-s2-spec.md 3.2·3.4
// 설계: dev-notes/document/s1-screens.md, p4-s1-screens.md, document-workflow/p6-s1-screens.md(+ p6a 3.2)
//       API: s2-spec.md 4장, p4-s2-spec.md, p6-s2-spec.md
// 스프린트 3: 파일 영역 DOC-SC-07·08(p4-s1-screens, API A11~A14 — document-files/s4-basis.md)
//           P8 점검표 D10·D12·D11(p8-s1-screens): 점검표 섹션·[매일 항목 모두 O]·작성 안 함(SC-13)·되돌리기·주 묶음 줄·주 묶음 상세
//           P9(C4 S5): DOC-SC-02 주기 양식 칸 · DOC-SC-14 주기 문서 날짜 선택(doc-requirements/p9-s1-screens.md 5·6장, REQ-A06·A07)
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const EDITABLE = ['draft', 'rejected', 'correcting'];  // P6: 정정 중도 수정·작성완료
  const COMPLETABLE = ['draft', 'rejected', 'correcting'];
  const REASON_MAX = 200;
  const REQUIREMENT = { lot: '⚙ 입고', batch: '⚙ 생산', periodic: '⚙ 주기' };  // periodic: P9 규칙을 P8 S4에서 앞당김(D-136)
  const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];
  const dow = (day) => WEEKDAY[new Date(`${day}T00:00:00Z`).getUTCDay()];
  // P8 F29 최근 값 제안(D12 공정명 — p8-s0 F5). 화면이 아는 양식 필드 목록
  const RECENT_FIELDS = { D12: ['process_name'] };
  const WEEK_TYPES = ['D10', 'D12'];  // 주 묶음 양식(DOC BUNDLE_UNITS week · REQ WEEK_BUNDLE_TYPES와 같음)
  // P12 출력: 출력하는 양식(WF PRINT_SHEETS)과 출력 가능 상태(작성중·반려·작성 안 함 제외).
  // CCP = 문서 1건 = 종이 1장, D03 = 그 문서의 입고일 장(p12-d03-policy.md 11), D10 = 그 문서의 주(주말 포함 — DP-12)
  const PRINT_TYPES = ['CCP-1P', 'CCP-2B', 'CCP-3P', 'D03', 'D10', 'D12', 'D11'];  // D11 = 그 달(DP-17)
  const WEEK_PRINT_TYPES = ['D10', 'D12'];  // 주 묶음 [주 출력](DP-12·13)
  const PRINTABLE = ['completed', 'submitted', 'approved', 'correcting'];
  // P12 DP-19 첨부 원본 인쇄(D01·D02 등 증빙 파일): 사진은 인쇄용 페이지(/print/?files=…)가 A4에 맞춰 한 장씩,
  // PDF는 화면 밖 iframe에서 브라우저 PDF 인쇄 — 안 되는 브라우저면 새 탭으로 열어 거기서 인쇄
  const isPdf = (x) => x.mime_type === 'application/pdf';
  function printImages(ids) {
    if (ids.length) window.open(`/print/?files=${ids.join(',')}&auto=1`, '_blank');
  }
  function printPdf(fileId) {
    const url = `/api/v1/files/${fileId}`;
    document.querySelectorAll('iframe[data-te-pdf-print]').forEach((f) => f.remove());
    const frame = document.createElement('iframe');
    frame.dataset.tePdfPrint = String(fileId);
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText = 'position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;pointer-events:none';
    frame.addEventListener('load', () => {
      setTimeout(() => {
        try { frame.contentWindow.focus(); frame.contentWindow.print(); } catch (e) { window.open(url, '_blank', 'noopener'); }
      }, 300);
    });
    frame.src = url;
    document.body.appendChild(frame);
  }
  // P8 점검표 섹션: 1행 섹션이고 필드에 표시용 키 group(관리 구분)이 있으면 종이처럼 표로(p8-s1-screens 2장)
  const isChecklist = (section) => !section.repeat && section.fields.some((fd) => fd.group);
  const isResult = (fd) => fd.type === 'select' && (fd.options || []).includes('O') && (fd.options || []).includes('X');
  // [매일 항목 모두 O] 대상: 결과 필드 중 날짜 규칙(na_default)·기본값(initial)이 없는 것(D10 13 · D12 15 · D11 9)
  const isDaily = (fd) => isResult(fd) && !('na_default' in fd) && !('initial' in fd);
  function checkCounts(schema, d) {
    const c = { O: 0, X: 0, NA: 0, blank: 0 };
    let found = false;
    // 서버 F26 check_counts(validation.check_counts)와 같은 기준: 반복 아닌 섹션의 O/X 선택 필드 전부
    schema.sections.filter((s) => !s.repeat).forEach((s) => {
      const v = ((d.sections.find((x) => x.section_def === s.key) || {}).values) || {};
      s.fields.filter(isResult).forEach((fd) => { found = true; c[['O', 'X', 'NA'].includes(v[fd.key]) ? v[fd.key] : 'blank'] += 1; });
    });
    return found ? c : null;
  }
  const countsText = (c) => (c ? `O ${c.O} · X ${c.X} · 해당 없음 ${c.NA}${c.blank ? ` · <b>빈칸 ${c.blank}</b>` : ' (빈칸 0)'}` : '');

  function today(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  // P9 (DOC-SC-02·14): 오늘(Asia/Seoul), 규칙 설명, A06 오류 문구
  const seoulDay = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  function periodicRuleText(rule) {
    const same = (a) => a.length === rule.weekdays.length && a.every((n, i) => n === rule.weekdays[i]);
    const span = same([1, 2, 3, 4, 5]) ? '월~금' : rule.weekdays.map((n) => WEEKDAY[n % 7]).join('·');
    return rule.cadence === 'weekly' ? '매주 (그 주 월요일)' : `${span} 매일`;
  }
  function periodicOpenError(r) {
    const code = r.data && r.data.code;
    if (code === 'TEMPLATE_INACTIVE' || code === 'TEMPLATE_NOT_FOUND') return '이 양식의 사용 중인 버전이 없습니다. 관리자에게 알리세요.';
    if (code === 'NOT_PERIODIC') return '주기 양식이 아닙니다. (규칙 파일이 바뀐 경우 — 화면을 새로 고치세요)';
    if (code === 'VALIDATION_ERROR') return '날짜를 고르세요.';
    return T.errorText(r);
  }

  // ---------------------------------------------------------------- 판정 계산 (서버 validation.evaluate와 같은 규칙)
  // 비교할 값이 비어 있으면 null. 화면 표시용이며 저장 값은 서버가 계산한다(P4-S2-Q5).
  function compare(item, value) {
    if (value === undefined || value === null || value === '') return null;
    if ('eq' in item && value !== item.eq) return false;
    if ('in' in item && !item.in.includes(value)) return false;
    const numeric = ['min', 'max', 'gt', 'lt'].some((k) => k in item);
    if (numeric && typeof value !== 'number') return false;
    if ('min' in item && !(value >= item.min)) return false;
    if ('max' in item && !(value <= item.max)) return false;
    if ('gt' in item && !(value > item.gt)) return false;
    if ('lt' in item && !(value < item.lt)) return false;
    return true;
  }
  function evaluate(cond, values) {
    const v = values || {};
    if (cond.all) {
      const r = cond.all.map((i) => compare(i, v[i.field]));
      if (r.includes(false)) return false;
      return r.includes(null) ? null : true;
    }
    const r = (cond.any || []).map((i) => compare(i, v[i.field]));
    if (r.includes(true)) return true;
    return r.includes(null) ? null : false;
  }
  function withComputed(section, values) {
    const out = { ...(values || {}) };
    section.fields.filter((fd) => fd.computed).forEach((fd) => {
      const r = evaluate(fd.computed, out);
      if (r === null) delete out[fd.key]; else out[fd.key] = r ? fd.computed.then : fd.computed.else;
    });
    return out;
  }
  const isNonconforming = (section, values) => !!section.nonconforming && evaluate(section.nonconforming, withComputed(section, values)) === true;
  const isSystem = (fd) => fd.readonly || !!fd.computed;
  const hasComputed = (section) => section.fields.some((fd) => fd.computed);
  const optionLabel = (fd, v) => (fd.option_labels && fd.option_labels[v]) || v;
  const fmtMinutes = (m) => `${Math.floor(m / 60)}시간 ${m % 60}분`;

  // 문서 단위 LOT 문서(D01·D02·D03)의 머리 정보: 품명·매입처(P6a-S1 DOC-SC-04). info 값이 없으면 빈 배열
  function lotInfo(d) {
    const info = (d.sections || []).find((x) => x.section_def === 'info');
    const v = (info && info.values) || {};
    return [v.item_name, v.supplier_name].filter(Boolean);
  }
  // 업무 대상 표시 (DOC-SC-01·03·04)
  function targetText(d) {
    const refs = d.refs || [];
    if (!d.record_key || !refs.length) return d.subject || '-';
    const docLevel = refs.filter((r) => r.section_id === null);
    const parts = docLevel.map((r) => {
      if (r.production_batch_id !== null) return `배치 ${r.label || r.production_batch_id}${r.process_code ? ` · ${r.process_code}` : ''}`;
      if (r.lot_id !== null) return [`LOT ${r.label || r.lot_id}`, ...lotInfo(d)].join(' · ');
      return r.label || r.process_code || '-';
    });
    const rowLots = refs.filter((r) => r.section_id !== null && r.lot_id !== null);
    if (rowLots.length) parts.push(`LOT ${rowLots.length}건 (${rowLots.map((r) => r.label || r.lot_id).join(', ')})`);
    else if (!docLevel.length) parts.push('LOT 0건');
    return parts.join(' / ');
  }
  // 문서 상세용: 같은 문구에 LOT마다 "LOT별 연결 문서"(REQ-SC-05) 링크(REQ-S1-Q4)
  function targetHtml(d) {
    const refs = d.refs || [];
    if (!d.record_key || !refs.length) return esc(d.subject || '-');
    const lotLink = (r) => `<a href="#" class="te-lot-link" data-lot="${r.lot_id}" title="이 LOT의 연결 문서">${esc(r.label || r.lot_id)}</a>`;
    const docLevel = refs.filter((r) => r.section_id === null);
    const parts = docLevel.map((r) => {
      // P11 S5 r2: 배치 이름 = 생산지시·실적의 그 배치(생산 화면이 있을 때만 링크)
      if (r.production_batch_id !== null) {
        const name = T.productionPage()
          ? `<a href="#" class="te-lot-link" data-prod-batch="${r.production_batch_id}" title="생산 기록(생산지시·실적)">${esc(r.label || r.production_batch_id)}</a>`
          : esc(r.label || r.production_batch_id);
        return `배치 ${name}${r.process_code ? ` · ${esc(r.process_code)}` : ''}`;
      }
      if (r.lot_id !== null) return [`LOT ${lotLink(r)}`, ...lotInfo(d).map(esc)].join(' · ');
      return esc(r.label || r.process_code || '-');
    });
    const rowLots = refs.filter((r) => r.section_id !== null && r.lot_id !== null);
    if (rowLots.length) parts.push(`LOT ${rowLots.length}건 (${rowLots.map(lotLink).join(', ')})`);
    else if (!docLevel.length) parts.push('LOT 0건');
    return parts.join(' / ');
  }
  // 측정일시(datetime) 행이 있는 양식의 기간: 작업일 ~ 마지막 측정일(D-051 F11, 저장 컬럼 없음)
  function periodText(schema, d) {
    const dates = [];
    schema.sections.filter((s) => s.repeat).forEach((s) => s.fields.filter((fd) => fd.type === 'datetime').forEach((fd) => {
      d.sections.filter((x) => x.section_def === s.key && x.values[fd.key]).forEach((x) => dates.push(String(x.values[fd.key]).slice(0, 10)));
    }));
    if (!schema.sections.some((s) => s.repeat && s.fields.some((fd) => fd.type === 'datetime'))) return '';
    const last = dates.length ? dates.sort()[dates.length - 1] : null;
    const label = d.template && d.template.type_code === 'CCP-2B' ? '건조 기간' : '측정 기간';
    return `<span id="tePeriod">${label} <b>${esc(d.work_date)} ~ ${esc(last && last > d.work_date ? last : d.work_date)}</b> <span class="te-hint">(마지막 측정일 기준)</span></span>`;
  }
  // 정정 진행 중이면 배지 옆 `정정` 꼬리표(정정 중 상태는 배지 자체가 "정정 중", DOC-SC-01·04)
  const correctionTag = (status, correcting) => (correcting && status !== 'correcting' ? ' <span class="badge te-chip-fix">정정</span>' : '');
  const statusCell = (status, correcting) => `${T.statusBadge(status)}${correctionTag(status, correcting)}`;
  // P7 묶음 상태 칸: 상태별 개수(0 생략, 순서 고정) + 정정 진행 수는 맨 뒤 따로 "정정 n"(P7-S5-Q3 a — 서버 status_counts 그대로)
  const STATUS_ORDER = ['draft', 'completed', 'submitted', 'approved', 'rejected', 'correcting', 'skipped'];
  const statusSummary = (counts, correcting) => STATUS_ORDER.filter((k) => counts[k])
    .map((k) => `<span class="te-count">${T.statusBadge(k)} ${counts[k]}</span>`).join(' ')
    + (correcting ? ` <span class="te-count"><span class="badge te-chip-fix">정정</span> ${correcting}</span>` : '');
  const mmdd = (day) => String(day || '').slice(5);
  // DOC-SC-01 묶음 줄(P7 Q7): 육안검사(D03)는 입고일마다 1줄. 필터 중이면 "D03 필터 n / 전체 m건"(검토 A3 — S5에서 판단)
  // P14 DOC-SC-10: "▸ 내 칸", 내 칸이 2개면 "▸ 내 칸 2개"(r7 — 예전 "내 차례", D-202 Q2 b: 칸 사이 순서 없음)
  const myTurn = (slots) => (slots && slots.length ? ` · <b class="te-my-turn">▸ 내 칸${slots.length > 1 ? ` ${slots.length}개` : ''}</b>` : '');
  const bundleRow = (b) => (b.bundle_unit === 'week' ? weekRow(b) : `
            <tr class="te-row-link te-row-bundle" data-bundle="${b.work_date}">
              <td><span class="badge te-chip-bundle">묶음</span></td>
              <td>${esc(b.template_name)} <span class="te-hint">(묶음)</span></td>
              <td>입고일 ${mmdd(b.work_date)} · ${b.count !== b.total ? `${esc(b.type_code)} 필터 ${b.count} / 전체 ${b.total}건` : `${esc(b.type_code)} ${b.count}건`}</td>
              <td>${b.work_date}</td>
              <td><span class="te-hint">–</span></td>
              <td>${T.peopleHtml(T.ownersOf(b.type_code))}</td>
              <td>${statusSummary(b.status_counts, b.correcting_count)}</td>
              <td>${b.requirement ? `<span class="te-req">${REQUIREMENT[b.requirement]}</span>` : '<span class="te-hint">–</span>'}</td>
              <td><span class="te-hint">–</span></td>
            </tr>`);
  // P8 주 묶음 줄(D10·D12, p8-s1-screens 5장): 작업일 칸 = 월~금, 대상 = n일(주말 문서도 그 주 줄에 셈)
  const weekRow = (b) => `
            <tr class="te-row-link te-row-bundle" data-week="${b.work_date}" data-week-type="${esc(b.type_code)}">
              <td><span class="badge te-chip-bundle">주</span></td>
              <td>${esc(b.template_name)} <span class="te-hint">(주)</span></td>
              <td>${b.count !== b.total ? `필터 ${b.count} / 전체 ${b.total}일` : `${b.count}일`}</td>
              <td class="te-nowrap">${mmdd(b.work_date)}~${mmdd(b.period_end)}</td>
              <td><span class="te-hint">–</span></td>
              <td>${T.peopleHtml(T.ownersOf(b.type_code))}</td>
              <td>${statusSummary(b.status_counts, b.correcting_count)}</td>
              <td><span class="te-req">${REQUIREMENT[b.requirement] || '–'}</span></td>
              <td><span class="te-hint">–</span></td>
            </tr>`;
  // D03 최종판정 강조(DOC-SC-03·04, P7 Q4): 검사 항목에 "불량"이 있는데 최종판정이 적합이면 안내(저장·작성완료는 막지 않음)
  const VERDICT_FOCUS_TYPES = ['D03'];
  const verdictFocus = (typeCode, field) => VERDICT_FOCUS_TYPES.includes(typeCode) && field.key === 'verdict';
  const verdictWarn = (section, values) => values.verdict === 'PASS'
    && section.fields.some((fd) => fd.type === 'select' && (fd.options || []).includes('불량') && values[fd.key] === '불량');
  const VERDICT_HINT = 'ⓘ 검사 항목에 "불량"이 있습니다 — 최종판정을 확인하세요';
  function shiftDay(day, n) {
    const d = new Date(`${day}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  }
  const requirementChip = (d) => (d.requirement ? `<span class="badge te-chip-req">${REQUIREMENT[d.requirement]} 작성 요구</span>` : '');

  // P10 문서함 탭(p10-s1-screens 3장): 마지막으로 연 탭을 이 브라우저에 기억(실패해도 기본 탭 — 화면 설정일 뿐)
  const TAB_KEY = 'te-docbox-tab';
  const readTab = () => { try { return localStorage.getItem(TAB_KEY); } catch (e) { return null; } };
  const saveTab = (tab) => { try { localStorage.setItem(TAB_KEY, tab); } catch (e) { /* 기억 못 해도 됨 */ } };
  const TODO_STATUS_NOTE = { missing: '<span class="badge te-badge-missing">문서 없음</span>' };
  const GROUP_EMPTY = { adhoc: '해당 양식 없음 (비정기 기구 점검·품질 점검 문서가 들어올 자리)' };

  const Doc = {
    title: '문서함',
    tab: null,
    todoState: { date: '', mine: false },
    root: null,
    templates: null,
    filters: { from: today(-6), to: today(0), template_id: '', status: '', target: '', mine: false, assigned: false, correcting: false, page: 1 },
    form: null,
    devDrafts: [],

    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      this.detailBack = null;
      // P11(p11-s2-spec 4장): CCP 대시보드에서 열면 [뒤로]는 대시보드(그 기준일), 이탈 줄 [열기]는 개선조치 영역으로
      this.openFocus = intent && intent.documentId ? { deviationNew: intent.deviationNew ?? null, focus: intent.focus || null } : null;
      if (intent && intent.documentId && intent.back && intent.back.page) this.detailBack = { page: intent.back.page, intent: intent.back.intent };
      if (intent && intent.bundleDay) this.showBundle(intent.bundleDay, intent.origin || { page: 'list' });
      else if (intent && intent.documentId) this.showDetail(intent.documentId);
      else this.showList();
    },

    async loadTemplates() {
      if (!this.templates) {
        const r = await api.get('templates');
        this.templates = r.ok ? r.data.items : [];
      }
      return this.templates;
    },

    rerenderTopBar(redraw) {
      T.bindTopBar(this.root, redraw);
    },

    // ================================================= DOC-SC-01 목록
    async showList(tab) {
      this.detailBack = null;
      this.tab = tab || this.tab || (readTab() === 'all' ? 'all' : 'todo');
      saveTab(this.tab);
      if (this.tab === 'todo') { this.showTodo(); return; }
      const f = this.filters;
      const templates = await this.loadTemplates();
      const statusOptions = ['', 'draft', 'completed', 'submitted', 'approved', 'rejected', 'correcting', 'skipped']
        .map((s) => `<option value="${s}" ${f.status === s ? 'selected' : ''}>${s ? T.STATUS[s].label : '전체'}</option>`).join('');
      const templateOptions = ['<option value="">전체</option>']
        .concat(templates.map((t) => `<option value="${t.template_id}" ${String(f.template_id) === String(t.template_id) ? 'selected' : ''}>${esc(t.name)} v${t.version}</option>`))
        .join('');
      // [육안검사 오늘](P7 DOC-SC-01): 오늘 묶음 상세(DOC-SC-10)를 연다(P6a-S1-Q6 목록 필터 대체)
      const d03 = templates.find((t) => t.type_code === 'D03');
      // P12 D11 [월 출력](S1 7장): 양식 필터가 D11일 때만 [월 ▾] + [월 출력]
      const d11Ids = templates.filter((t) => t.type_code === 'D11').map((t) => String(t.template_id));
      const thisMonth = today(0).slice(0, 7);
      this.root.innerHTML = `
        <div class="fade-in" id="teDocList">
          ${this.boxHead()}
          <div class="card">
            <div class="te-filters">
              <div class="form-group"><label class="form-label">작업일 시작</label><input type="date" class="form-control" id="fFrom" value="${f.from}"></div>
              <div class="form-group"><label class="form-label">작업일 종료</label><input type="date" class="form-control" id="fTo" value="${f.to}"></div>
              <div class="form-group"><label class="form-label">양식</label><select class="form-control" id="fTemplate">${templateOptions}</select></div>
              <div class="form-group"><label class="form-label">상태</label><select class="form-control" id="fStatus">${statusOptions}</select></div>
              <div class="form-group"><label class="form-label">대상</label><input class="form-control" id="fTarget" maxlength="50" placeholder="LOT·배치 번호" value="${esc(f.target)}"></div>
              <label class="te-check"><input type="checkbox" id="fMine" ${f.mine ? 'checked' : ''}> 내가 작성</label>
              <label class="te-check" title="내가 담당자인 양식의 문서(역할 설정)"><input type="checkbox" id="fAssigned" ${f.assigned ? 'checked' : ''}> 내 담당 양식</label>
              <label class="te-check" title="정정 중 + 정정 꼬리표가 붙은 작성완료·결재중"><input type="checkbox" id="fCorrecting" ${f.correcting ? 'checked' : ''}> 정정 진행 중 전체</label>
              <button class="btn btn-secondary" id="fSearch">조회</button>
              ${d03 ? '<button class="btn btn-secondary" id="fD03Today" title="오늘 입고된 LOT의 육안검사 묶음 상세">육안검사 오늘</button>' : ''}
              <span class="te-month-print" id="fMonthWrap" ${d11Ids.includes(String(f.template_id)) ? '' : 'hidden'}>
                <input type="month" class="form-control" id="fMonth" value="${(f.month || thisMonth)}" max="${thisMonth}" title="출력할 달">
                <button class="btn btn-secondary" id="fMonthPrint" title="그 달 방충방서점검표(주 문서 4~5주)">월 출력</button>
              </span>
            </div>
            <div class="te-table-wrap" id="teListBody">${this.skeleton()}</div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showList());
      this.bindBoxHead();
      const $ = (id) => this.root.querySelector(id);
      const search = () => {
        Object.assign(f, {
          from: $('#fFrom').value, to: $('#fTo').value, template_id: $('#fTemplate').value,
          status: $('#fStatus').value, target: $('#fTarget').value.trim(),
          mine: $('#fMine').checked, assigned: $('#fAssigned').checked, correcting: $('#fCorrecting').checked, page: 1,
        });
        this.loadList();
      };
      $('#fSearch').addEventListener('click', search);
      $('#fTemplate').addEventListener('change', () => { $('#fMonthWrap').hidden = !d11Ids.includes($('#fTemplate').value); });
      $('#fMonthPrint').addEventListener('click', () => {
        const month = $('#fMonth').value || thisMonth;
        f.month = month;
        window.open(`/print/?kind=monthly&type=D11&month=${month}`, '_blank');
      });
      if (d03) {
        $('#fD03Today').addEventListener('click', () => this.showBundle(today(0), { page: 'list' }));
      }
      $('#fTarget').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });
      this.loadList();
    },

    // ================================================= DOC-SC-01 문서함 머리(P10): 탭 + [새 문서]
    boxHead() {
      const tab = (key, label) => `<button class="btn btn-sm ${this.tab === key ? 'btn-primary' : 'btn-secondary'}" data-tab="${key}">${label}</button>`;
      return `
        ${T.topBar('문서함', '작성 필요 · 전체 문서 — 문서 작성·조회·결재', null, { temp: false })}
        <div class="te-tabs te-box-tabs" id="teBoxTabs">
          ${tab('todo', '작성 필요 <span id="teTodoCount"></span>')} ${tab('all', '전체 문서')}
          <span style="flex:1"></span>
          <button class="btn btn-primary btn-sm" id="btnNew">+ 새 문서</button>
        </div>`;
    },
    bindBoxHead() {
      this.root.querySelectorAll('#teBoxTabs [data-tab]').forEach((b) => b.addEventListener('click', () => this.showList(b.dataset.tab)));
      this.root.querySelector('#btnNew').addEventListener('click', () => this.showPicker());
    },

    // ================================================= DOC-SC-15 작성 필요 탭(P10, REQ-A08)
    showTodo() {
      const s = this.todoState;
      if (!s.date) s.date = seoulDay();
      this.root.innerHTML = `
        <div class="fade-in" id="teTodoTab">
          ${this.boxHead()}
          <div class="card">
            <div class="te-filters te-todo-bar">
              <div class="form-group"><label class="form-label">기준일</label><input type="date" class="form-control" id="tdDate" value="${s.date}" max="${seoulDay()}"></div>
              <span class="te-hint" id="tdDow">(${dow(s.date)})</span>
              <label class="te-check" title="내가 담당자·작성 권한자이거나 점검자로 지정된 문서(작성자는 보지 않음). 문서 없음 줄은 빠짐"><input type="checkbox" id="tdMine" ${s.mine ? 'checked' : ''}> 내 문서</label>
              <span style="flex:1"></span>
              <span class="te-hint" id="tdSummary"></span>
              <span id="tdOlderSlot"></span>
            </div>
            <div id="teTodoBody">${this.skeleton()}</div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showTodo());
      this.bindBoxHead();
      const $ = (sel) => this.root.querySelector(sel);
      $('#tdDate').addEventListener('change', () => { if ($('#tdDate').value) { s.date = $('#tdDate').value; this.showTodo(); } });
      $('#tdMine').addEventListener('change', () => { s.mine = $('#tdMine').checked; this.loadTodo(); });
      this.loadTodo();
    },

    todoRow(r) {
      const day = r.week_start ? `${mmdd(r.week_start)} 주` : `${mmdd(r.work_date)} (${dow(r.work_date)})`;
      const tags = (r.tags || []).map((t) => ` <span class="badge te-chip-tag">${esc(t)}</span>`).join('');
      let target = esc(r.target_summary || '-');
      if (r.requirement === 'periodic') target = '<span class="te-req">⚙ 주기</span>';
      if (r.bundle) target = `입고 ${mmdd(r.bundle.received_date)} <span class="te-hint">(D03 ${r.bundle.count}건)</span>`;
      let button = `<button class="btn btn-secondary btn-sm" data-open="${r.document_id}">열기</button>`;
      if (r.kind === 'missing') button = `<button class="btn btn-primary btn-sm" data-make="${esc(r.type_code)}" data-day="${r.work_date}" ${api.staffId ? '' : 'disabled'}>만들기</button>`;
      else if (r.bundle) button = `<button class="btn btn-secondary btn-sm" data-bundle-day="${r.bundle.received_date}">열기</button>`;
      return `
        <tr data-todo-kind="${r.kind}" data-type="${esc(r.type_code)}" data-day="${r.work_date}">
          <td>${day}</td>
          <td>${esc(r.type_code)} ${esc(r.template_name || '')}${tags}</td>
          <td>${target}</td>
          <td>${r.kind === 'missing' ? TODO_STATUS_NOTE.missing : T.statusBadge(r.status)}</td>
          <td title="점검자/담당자">${r.inspector_id ? T.personHtml(r.inspector_id) : (r.kind === 'missing' ? '<span class="te-hint">–</span>' : T.peopleHtml(r.owner_ids, { empty: '<span class="te-hint">–</span>' }))}</td>
          <td>${button}</td>
        </tr>`;
    },

    todoTable(rows) {
      return `<table class="data-table te-todo-table"><tbody>${rows.map((r) => this.todoRow(r)).join('')}</tbody></table>`;
    },

    async loadTodo() {
      const s = this.todoState;
      const body = this.root.querySelector('#teTodoBody');
      if (!api.staffId) { body.innerHTML = '<div class="te-empty">현재 사용자를 선택하세요. 작성 필요 목록은 현재 사용자로 조회합니다.</div>'; return; }
      body.innerHTML = this.skeleton();
      const q = new URLSearchParams({ date: s.date });
      if (s.mine) q.set('mine', '1');
      const r = await api.get(`todo?${q}`);
      if (!this.root.querySelector('#teTodoBody')) return;  // 그사이 다른 화면
      if (!r.ok) {
        body.innerHTML = `<div class="te-empty">${esc(T.errorText(r))}</div>`;
        return;
      }
      const data = r.data;
      const counts = data.counts;
      const total = Object.values(counts).reduce((a, b) => a + b, 0);
      const countEl = this.root.querySelector('#teTodoCount');
      if (countEl) countEl.textContent = String(total);
      this.root.querySelector('#tdSummary').textContent = data.groups.map((g) => `${g.label} ${g.count}`).join(' · ');
      const parts = [];
      if ((data.warnings || []).includes('RULES_INVALID')) {
        parts.push('<div class="te-status-note" id="tdRulesInvalid">주기 규칙 파일 오류로 "문서 없음"을 계산하지 못했습니다. 나머지 줄은 그대로 보입니다.</div>');
      }
      if (!total && !data.awaiting_submit.count && !data.older.count) {
        parts.push('<div class="te-empty" id="tdEmpty">작성할 문서가 없습니다.</div>');
      }
      data.groups.forEach((g) => {
        const empty = !g.count ? `<div class="te-hint te-todo-empty">${!g.has_forms ? (GROUP_EMPTY[g.key] || '해당 양식 없음') : '할 일 없음'}</div>` : '';
        const past = g.past.count ? `
          <details class="te-todo-past" data-past="${g.key}"><summary>지난 미완료 ${g.past.count}건 (${mmdd(g.past.from)} ~ ${mmdd(g.past.to)})</summary>
            ${this.todoTable(g.past.rows)}</details>` : '';
        parts.push(`
          <div class="te-todo-group" data-group="${g.key}">
            <div class="te-section-title">── ${esc(g.label)} (${g.count}) ──</div>
            ${g.rows.length ? this.todoTable(g.rows) : ''}${empty}${past}
          </div>`);
      });
      if (data.awaiting_submit.count) {
        parts.push(`
          <div class="te-todo-group" data-group="awaiting">
            <div class="te-section-title">── 상신 대기 (${data.awaiting_submit.count}) ── <span class="te-hint">작성완료했지만 상신 안 함(상신 취소 포함) · 배지에는 안 셈</span></div>
            ${this.todoTable(data.awaiting_submit.rows)}
          </div>`);
      }
      // ISS-037(C5 S6 r2): 30일 넘은 미완료 링크는 위쪽 요약 줄 옆(맨 아래에서는 찾기 어려움)
      const slot = this.root.querySelector('#tdOlderSlot');
      slot.innerHTML = data.older.count ? `<a href="#" id="tdOlder" class="te-todo-older">30일 넘은 미완료 ${data.older.count}건 → 전체 문서</a>` : '';
      body.innerHTML = parts.join('');
      body.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => this.showDetail(Number(b.dataset.open))));
      body.querySelectorAll('[data-bundle-day]').forEach((b) => b.addEventListener('click', () => this.showBundle(b.dataset.bundleDay, { page: 'list' })));
      body.querySelectorAll('[data-make]').forEach((b) => b.addEventListener('click', () => this.makeMissing(b, b.dataset.make, b.dataset.day)));
      slot.querySelector('#tdOlder')?.addEventListener('click', (e) => {
        e.preventDefault();
        // 전체 문서 탭: 그 전 1년 · 상태는 전체(작성중·반려·정정 중을 한 번에 고르는 필터가 없음)
        Object.assign(this.filters, { from: shiftDay(data.older.before, -365), to: shiftDay(data.older.before, -1), template_id: '', status: '', target: '', mine: false, assigned: false, correcting: false, page: 1 });
        this.showList('all');
      });
    },

    // [만들기](P10 S1-Q3): 문서 없음 줄 → P9 A06 → 새로 만들었으면 작성 폼, 이미 있으면 토스트 + 상세
    async makeMissing(btn, typeCode, day) {
      btn.disabled = true;
      const r = await api.post('periodic-documents', { type_code: typeCode, date: day });
      if (!r.ok) { btn.disabled = false; T.toast(periodicOpenError(r), 'error'); return; }
      const id = r.data.document_id;
      if (r.data.result === 'existing') {
        T.toast(`${r.data.work_date.slice(5)} 문서가 이미 있습니다(#${id} ${T.STATUS[r.data.status]?.label || r.data.status}).`, 'info');
        this.showDetail(id);
        return;
      }
      const d = await api.get(`documents/${id}`);
      if (!d.ok) { T.toast(T.errorText(d), 'error'); this.showDetail(id); return; }
      this.openForm({ document: d.data });
    },

    skeleton() {
      const row = '<tr class="te-skeleton">' + '<td>.</td>'.repeat(8) + '</tr>';
      return `<table class="data-table"><tbody>${row.repeat(3)}</tbody></table>`;
    },

    async loadList() {
      const f = this.filters;
      const body = this.root.querySelector('#teListBody');
      body.innerHTML = this.skeleton();
      if ((f.mine || f.assigned) && !api.staffId) {
        body.innerHTML = '<div class="te-empty">"내가 작성/내 담당 양식"은 현재 사용자를 먼저 선택하세요.</div>';
        return;
      }
      const q = new URLSearchParams();
      if (f.from) q.set('from', f.from);
      if (f.to) q.set('to', f.to);
      if (f.template_id) q.set('template_id', f.template_id);
      if (f.status) q.set('status', f.status);
      if (f.target) q.set('target', f.target);
      if (f.mine) q.set('author_id', api.staffId);
      if (f.assigned) q.set('owner_id', api.staffId);  // P14 S4-C1: 내가 담당자인 양식
      if (f.correcting) q.set('correcting', 'true');
      q.set('page', f.page);
      const r = await api.get(`documents?${q}`);
      if (!r.ok) {
        T.toast(T.errorText(r), 'error');
        body.innerHTML = `<div class="te-empty">${esc(r.data?.message || '조회에 실패했습니다.')}</div>`;
        return;
      }
      const { items, total, page, page_size: size } = r.data;
      if (!items.length) {
        body.innerHTML = '<div class="te-empty">조건에 맞는 문서가 없습니다.<br><br><button class="btn btn-primary btn-sm" id="btnNew2">+ 새 문서</button></div>';
        body.querySelector('#btnNew2').addEventListener('click', () => this.showPicker());
        return;
      }
      const pages = Math.max(1, Math.ceil(total / size));
      body.innerHTML = `
        <table class="data-table">
          <thead><tr><th>번호</th><th>양식(버전)</th><th>대상</th><th>작업일</th><th>작성자</th><th>담당자</th><th>상태</th><th>작성 요구</th><th>작성일</th></tr></thead>
          <tbody>${items.map((d) => d.kind === 'bundle' ? bundleRow(d) : `
            <tr class="te-row-link" data-id="${d.document_id}">
              <td>${d.document_id}</td>
              <td>${esc(d.template.name)} v${d.template.version}</td>
              <td>${esc(d.target_summary || d.subject || '-')}</td>
              <td>${d.work_date}</td>
              <td>${T.authorHtml(d, { short: true })}</td>
              <td>${T.peopleHtml(T.ownersOf(d.template.type_code))}</td>
              <td>${statusCell(d.status, d.correcting)}</td>
              <td>${d.requirement ? `<span class="te-req">${REQUIREMENT[d.requirement]}</span>` : '<span class="te-hint">–</span>'}</td>
              <td>${T.fmtDateTime(d.created_at)}</td>
            </tr>`).join('')}</tbody>
        </table>
        <div class="te-pager">
          <button class="btn btn-secondary btn-sm" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹</button>
          <span>${page} / ${pages} · 총 ${total}건 · ${size}건씩</span>
          <button class="btn btn-secondary btn-sm" data-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>›</button>
        </div>`;
      body.querySelectorAll('tr[data-id]').forEach((tr) =>
        tr.addEventListener('click', () => this.showDetail(Number(tr.dataset.id))));
      body.querySelectorAll('tr[data-bundle]').forEach((tr) =>
        tr.addEventListener('click', () => this.showBundle(tr.dataset.bundle, { page: 'list' })));
      body.querySelectorAll('tr[data-week]').forEach((tr) =>
        tr.addEventListener('click', () => this.showWeek(tr.dataset.weekType, tr.dataset.week, { page: 'list' })));
      body.querySelectorAll('button[data-page]').forEach((b) =>
        b.addEventListener('click', () => { f.page = Number(b.dataset.page); this.loadList(); }));
    },

    // 문서 상세 [뒤로/목록]: 묶음 상세에서 열었으면 그 묶음으로(P6a S6a-4 규칙 — 연 곳으로)
    goBack() {
      const back = this.detailBack;
      if (back && back.page) T.open(back.page, back.intent);
      else if (back && back.bundleDay) this.showBundle(back.bundleDay, back.origin);
      else if (back && back.week) this.showWeek(back.week.type, back.week.start, back.week.origin);
      else this.showList();
    },
    openFromWeek(documentId) {
      this.detailBack = { week: { type: this.week.type, start: this.week.start, origin: this.week.origin } };
      this.showDetail(documentId);
    },
    openFromBundle(documentId) {
      this.detailBack = { bundleDay: this.bundle.day, origin: this.bundle.origin };
      this.showDetail(documentId);
    },

    // ================================================= DOC-SC-10 육안검사 묶음 상세 (P7)
    // 진입: 목록 묶음 줄·[육안검사 오늘](origin list), LOT별 연결 문서의 입고일 링크(origin temp-lot-docs).
    // 데이터: REQ-A03 GET incoming-inspections?received_date= (X-Staff-Id — 내 칸 계산. r14: 헤더 선택, 화면은 사용자를 고른 뒤에만 엶)
    async showBundle(day, origin) {
      this.detailBack = null;
      const keep = this.bundle && this.bundle.day === day ? this.bundle.selected : new Set();
      this.bundle = { day, origin: origin || (this.bundle && this.bundle.origin) || { page: 'list' }, selected: keep, data: null };
      const B = window.TempEntryApproval && window.TempEntryApproval.batch;
      const head = `
        <div class="te-bundle-nav">
          <button class="btn btn-secondary btn-sm" id="bdPrev">◀ 전날</button>
          <b class="te-bundle-day">입고일 ${esc(day)}</b>
          <button class="btn btn-secondary btn-sm" id="bdNext">다음날 ▶</button>
          <span style="flex:1"></span>
          <button class="btn btn-secondary btn-sm" id="bdBack">뒤로</button>
        </div>`;
      this.root.innerHTML = `
        <div class="fade-in" id="teBundle">
          ${T.topBar('육안검사일지 묶음', '같은 입고일 LOT들의 육안검사(D03) — 일괄 상신·승인·점검자 지정')}
          <div class="card">${head}<div id="bdBody">${this.skeleton()}</div></div>
        </div>`;
      this.rerenderTopBar(() => this.showBundle(day, this.bundle.origin));
      const $ = (sel) => this.root.querySelector(sel);
      $('#bdPrev').addEventListener('click', () => this.showBundle(shiftDay(day, -1), this.bundle.origin));
      $('#bdNext').addEventListener('click', () => this.showBundle(shiftDay(day, 1), this.bundle.origin));
      $('#bdBack').addEventListener('click', () => {
        const o = this.bundle.origin;
        if (o.page === 'temp-lot-docs') T.open('temp-lot-docs', { lotId: o.lotId, back: o.back });
        else this.showList();
      });
      const body = $('#bdBody');
      if (!api.staffId) { body.innerHTML = '<div class="te-empty">현재 사용자를 선택하세요. 묶음 상세는 현재 사용자 기준으로 내 결재 대기를 보입니다.</div>'; return; }
      const [r, cfg] = await Promise.all([api.get(`incoming-inspections?received_date=${day}`), B ? B.config() : { max_items: 50 }]);
      if (!this.root.contains(body)) return;
      if (!r.ok) {
        T.toast(T.errorText(r), 'error');
        body.innerHTML = `<div class="te-empty">${esc(T.errorText(r))}</div>`;
        return;
      }
      this.bundle.data = r.data;
      this.bundle.max = cfg.max_items;
      this.renderBundle();
    },

    // 줄 → 일괄 모달 줄(approval.js Batch 모양)
    bundleRows() {
      const { data } = this.bundle;
      return data.lots.filter((l) => l.document).map((l) => {
        const x = l.document;
        return {
          document_id: x.document_id, lot: `${l.lot_number} · ${l.item_name}`, lot_number: l.lot_number,
          status: x.status, correcting: x.correcting, version: x.version, verdict: x.verdict, nonconforming: x.nonconforming,
          inspector_id: x.inspector_id, attempt: x.progress ? x.progress.attempt : null, my_slots: x.my_slots || [], progress: x.progress,
          can_submit: x.can_submit, submit_block: x.submit_block,  // P14: 일괄 상신 미리 표시(S1-Q7)
          can_write: x.can_write,  // r13 ROLE-R07(작성 안 함 등 문서별 쓰기)
        };
      });
    },

    renderBundle() {
      const { data, selected, max } = this.bundle;
      const body = this.root.querySelector('#bdBody');
      const lots = data.lots;
      if (!lots.length) {
        body.innerHTML = '<div class="te-empty" id="bdEmpty">이 날 입고된 LOT이 없습니다</div>';
        return;
      }
      const rows = this.bundleRows();
      const ids = new Set(rows.map((x) => x.document_id));
      [...selected].forEach((id) => { if (!ids.has(id)) selected.delete(id); });
      const picked = rows.filter((x) => selected.has(x.document_id));
      const n = {
        inspector: picked.filter((x) => EDITABLE.includes(x.status)).length,
        submit: picked.filter((x) => x.status === 'completed').length,
        approve: picked.reduce((n, x) => n + x.my_slots.length, 0),  // P14: 내 칸 수 합(겸직자는 문서당 2칸)
      };
      const over = picked.length > max;
      const btn = (id, label, count) => `<button class="btn ${count ? 'btn-primary' : 'btn-secondary'} btn-sm" id="${id}" ${!count || over ? 'disabled' : ''}>${label} (${count})</button>`;
      const s = data.summary;
      const approval = (x) => {
        if (x.status === 'approved') return '완료';
        if (x.status === 'submitted' && x.progress) return `승인 ${x.progress.approved}/${x.progress.total}${myTurn(x.my_slots)}`;
        if (x.progress && x.progress.status === 'cancelled') return '<span class="te-hint te-cancelled">취소됨</span>';  // P10: 최신 회차 상신 취소
        if (x.status === 'rejected') return '<span class="te-hint">반려</span>';
        return '<span class="te-hint">–</span>';
      };
      const assign = !!(data.permissions && data.permissions.assign_inspector);  // r13 ROLE-R08
      const missing = lots.filter((l) => !l.document);
      body.innerHTML = `
        <div class="te-bundle-summary" id="bdSummary">
          <span>D03 ${s.documents}건:</span> ${statusSummary(s.status_counts, s.correcting_count) || '<span class="te-hint">문서 없음</span>'}
          <span style="flex:1"></span><span>내 결재 대기 <b>${s.my_pending}</b></span>
        </div>
        <div class="te-bundle-actions">
          ${assign ? btn('bdInspector', '점검자 지정', n.inspector) : `<button class="btn btn-secondary btn-sm" id="bdInspector" disabled title="${esc(T.INSPECTOR_WHY)}">점검자 지정 (${n.inspector})</button>`} ${btn('bdSubmit', '선택 상신', n.submit)} ${btn('bdApprove', '선택 승인', n.approve)}
          <span class="te-hint" id="bdPicked">선택 ${picked.length}건${over ? ` — <span class="te-error-text">한 번에 ${max}건까지</span>` : ''}</span>
          <span style="flex:1"></span>
          <button class="btn btn-secondary btn-sm" id="bdPrint" title="이 입고일의 원료/부자재 육안검사일지(작성완료 뒤 문서만 검사 값)">출력</button>
        </div>
        ${assign ? '' : `<div class="te-perm-note" id="bdInspectorWhy">${esc(T.INSPECTOR_WHY)} ${T.roleLink()}</div>`}
        <div class="te-table-wrap"><table class="data-table" id="bdTable">
          <thead><tr><th class="te-check-col"><input type="checkbox" id="bdAll" ${rows.length && picked.length === rows.length ? 'checked' : ''} ${rows.length ? '' : 'disabled'} title="보이는 줄 전체"></th>
            <th>LOT</th><th>품목·매입처</th><th>수량</th><th>문서</th><th>상태</th><th>점검자</th><th>판정(현재)</th><th>승인본 판정</th><th>결재</th></tr></thead>
          <tbody>${lots.filter((l) => l.document).map((l) => {
            const x = l.document;
            return `<tr data-lot-row="${l.lot_id}" class="${selected.has(x.document_id) ? 'te-row-picked' : ''}">
              <td class="te-check-col"><input type="checkbox" data-pick="${x.document_id}" ${selected.has(x.document_id) ? 'checked' : ''}></td>
              <td class="mono">${esc(l.lot_number)}</td>
              <td>${esc(l.item_name)} · ${esc(l.supplier_name)}${l.material_kind ? ` <span class="te-hint">${esc(l.material_kind)}</span>` : ''}</td>
              <td>${esc(l.quantity || '-')}</td>
              <td><a href="#" class="te-lot-link" data-open-doc="${x.document_id}">#${x.document_id}</a></td>
              <td>${statusCell(x.status, x.correcting)}</td>
              <td>${T.personHtml(x.inspector_id)}</td>
              <td>${x.verdict ? `<span class="${x.verdict === 'FAIL' ? 'te-judge-ng' : ''}">${x.verdict === 'FAIL' ? '부적합' : '적합'}</span>` : '<span class="te-hint">–</span>'}</td>
              <td>${x.approved_verdict ? `${x.approved_verdict === 'FAIL' ? '<span class="te-judge-ng">부적합</span>' : '적합'} <span class="te-hint">${x.approved ? `${x.approved.attempt}회차` : ''}</span>` : '<span class="te-hint">–</span>'}</td>
              <td>${approval(x)}</td>
            </tr>`;
          }).join('') || '<tr><td colspan="10" class="te-hint">육안검사 문서가 없습니다.</td></tr>'}</tbody>
        </table></div>
        ${missing.length ? `<div class="te-bundle-missing" id="bdMissing">문서 없음: ${missing.map((l) => `<b class="mono">${esc(l.lot_number)}</b>`).join(', ')} <span class="te-hint">(작성 요구 미호출 — 작성 요구 화면에서 [다시 호출])</span></div>` : ''}`;
      const $ = (sel) => body.querySelector(sel);
      body.querySelectorAll('[data-pick]').forEach((c) => c.addEventListener('change', () => {
        const id = Number(c.dataset.pick);
        if (c.checked) selected.add(id); else selected.delete(id);
        this.renderBundle();
      }));
      $('#bdAll').addEventListener('change', (e) => {
        rows.forEach((x) => { if (e.target.checked) selected.add(x.document_id); else selected.delete(x.document_id); });
        this.renderBundle();
      });
      body.querySelectorAll('[data-open-doc]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        this.openFromBundle(Number(a.dataset.openDoc));
      }));
      const B = window.TempEntryApproval.batch;
      // P7 S5-16(사용자 결정): 일괄 처리 뒤 결과 [닫기]로 다시 읽을 때 선택을 비운다
      const after = {
        onDone: () => { this.bundle.selected = new Set(); this.showBundle(this.bundle.day, this.bundle.origin); },
        openDoc: (id) => { this.bundle.selected = new Set(); this.openFromBundle(id); },
      };
      $('#bdPrint').addEventListener('click', () => window.open(`/print/?kind=receiving&type=D03&date=${this.bundle.day}`, '_blank'));
      $('#bdApprove').addEventListener('click', () => B.openApprove(picked, { origin: 'bundle', ...after }));
      $('#bdSubmit').addEventListener('click', () => B.openSubmit(picked, data.approval_line, after));
      $('#bdInspector').addEventListener('click', () => B.guardOpen(async () => this.openInspector(picked, after, max)));
    },

    // ================================================= DOC-SC-10 주 묶음 상세 (P8 — D10·D12, p8-s1-screens 5장)
    // 데이터: REQ-A04 GET periodic-bundles?type_code=&week_start=(월요일, X-Staff-Id — 내 칸 계산. r14: 헤더 선택)
    async showWeek(type, start, origin) {
      this.detailBack = null;
      const keep = this.week && this.week.type === type && this.week.start === start ? this.week.selected : new Set();
      this.week = { type, start, origin: origin || (this.week && this.week.origin) || { page: 'list' }, selected: keep, data: null, max: 50 };
      const B = window.TempEntryApproval && window.TempEntryApproval.batch;
      const name = ((this.templates || []).find((t) => t.type_code === type) || {}).name || type;
      this.root.innerHTML = `
        <div class="fade-in" id="teWeek">
          ${T.topBar(`${name} — 주 묶음`, '하루 문서를 월~금으로 모아 일괄 상신·승인·점검자 지정·작성 안 함')}
          <div class="card">
            <div class="te-bundle-nav">
              <button class="btn btn-secondary btn-sm" id="wkPrev">◀ 전주</button>
              <b class="te-bundle-day" id="wkTitle">${esc(start)} (월) ~ ${esc(shiftDay(start, 4))} (금)</b>
              <button class="btn btn-secondary btn-sm" id="wkNext">다음주 ▶</button>
              <span style="flex:1"></span>
              <button class="btn btn-secondary btn-sm" id="wkBack">뒤로</button>
            </div>
            <div id="wkBody">${this.skeleton()}</div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showWeek(type, start, this.week.origin));
      const $ = (sel) => this.root.querySelector(sel);
      $('#wkPrev').addEventListener('click', () => this.showWeek(type, shiftDay(start, -7), this.week.origin));
      $('#wkNext').addEventListener('click', () => this.showWeek(type, shiftDay(start, 7), this.week.origin));
      $('#wkBack').addEventListener('click', () => this.showList());
      const body = $('#wkBody');
      if (!api.staffId) { body.innerHTML = '<div class="te-empty">현재 사용자를 선택하세요. 주 묶음은 현재 사용자 기준으로 내 결재 대기를 보입니다.</div>'; return; }
      const [r, cfg] = await Promise.all([api.get(`periodic-bundles?type_code=${encodeURIComponent(type)}&week_start=${start}`), B ? B.config() : { max_items: 50 }]);
      if (!this.root.contains(body)) return;
      if (!r.ok) { T.toast(T.errorText(r), 'error'); body.innerHTML = `<div class="te-empty">${esc(T.errorText(r))}</div>`; return; }
      this.week.data = r.data;
      this.week.max = cfg.max_items;
      this.renderWeek();
    },

    weekRows() {
      return this.week.data.days.filter((x) => x.document).map((x) => {
        const d = x.document;
        return {
          document_id: d.document_id, lot: `${mmdd(x.work_date)} (${WEEKDAY[x.weekday % 7]})`, status: d.status, correcting: d.correcting,
          version: d.version, verdict: d.nonconforming === true ? 'FAIL' : (d.nonconforming === false ? 'PASS' : null), nonconforming: d.nonconforming,
          inspector_id: d.inspector_id, attempt: d.progress ? d.progress.attempt : null, my_slots: d.my_slots || [], progress: d.progress,
          can_submit: d.can_submit, submit_block: d.submit_block,  // P14: 일괄 상신 미리 표시(S1-Q7)
          can_write: d.can_write,  // r13 ROLE-R07(작성 안 함 등 문서별 쓰기)
        };
      });
    },

    renderWeek() {
      const { data, selected, max } = this.week;
      const body = this.root.querySelector('#wkBody');
      const rows = this.weekRows();
      const ids = new Set(rows.map((x) => x.document_id));
      [...selected].forEach((id) => { if (!ids.has(id)) selected.delete(id); });
      const picked = rows.filter((x) => selected.has(x.document_id));
      const n = {
        inspector: picked.filter((x) => EDITABLE.includes(x.status)).length,
        submit: picked.filter((x) => x.status === 'completed').length,
        approve: picked.reduce((n, x) => n + x.my_slots.length, 0),  // P14: 내 칸 수 합(겸직자는 문서당 2칸)
        skip: picked.filter((x) => x.status === 'draft').length,
      };
      const assign = !!(data.permissions && data.permissions.assign_inspector);  // r13 ROLE-R08
      const over = picked.length > max;
      const btn = (id, label, count) => `<button class="btn ${count ? 'btn-primary' : 'btn-secondary'} btn-sm" id="${id}" ${!count || over ? 'disabled' : ''}>${label} (${count})</button>`;
      const s = data.summary;
      const approval = (x) => {
        if (x.status === 'approved') return '완료';
        if (x.status === 'submitted' && x.progress) return `승인 ${x.progress.approved}/${x.progress.total}${myTurn(x.my_slots)}`;
        if (x.progress && x.progress.status === 'cancelled') return '<span class="te-hint te-cancelled">취소됨</span>';  // P10: 최신 회차 상신 취소
        if (x.status === 'rejected') return '<span class="te-hint">반려</span>';
        return '<span class="te-hint">–</span>';
      };
      const counts = (c) => (c ? `O ${c.O} · <span class="${c.X ? 'te-judge-ng' : ''}">X ${c.X}</span> · NA ${c.NA}${c.blank ? ` · 빈칸 ${c.blank}` : ''}` : '–');
      const dayRow = (x) => {
        const d = x.document;
        const label = `${mmdd(x.work_date)} (${WEEKDAY[x.weekday % 7]})`;
        if (!d) return `<tr data-week-day="${x.work_date}" class="te-row-skipped"><td class="te-check-col"></td><td>${label}</td><td colspan="6" class="te-hint">문서 없음 — 아직 만들어지지 않은 날</td></tr>`;
        return `<tr data-week-day="${x.work_date}" class="${selected.has(d.document_id) ? 'te-row-picked' : ''} ${d.status === 'skipped' ? 'te-row-skipped' : ''}">
          <td class="te-check-col"><input type="checkbox" data-pick="${d.document_id}" ${selected.has(d.document_id) ? 'checked' : ''}></td>
          <td>${label}</td>
          <td><a href="#" class="te-lot-link" data-open-doc="${d.document_id}">#${d.document_id}</a></td>
          <td>${statusCell(d.status, d.correcting)}</td>
          <td>${T.personHtml(d.inspector_id)}</td>
          <td>${d.status === 'skipped' ? '<span class="te-hint">–</span>' : counts(d.check_counts)}</td>
          <td>${d.nonconforming ? '<span class="te-judge-ng">부적합</span>' : (d.nonconforming === false ? '적합' : '<span class="te-hint">–</span>')}</td>
          <td>${approval({ ...d, my_slots: d.my_slots || [] })}</td>
        </tr>`;
      };
      body.innerHTML = `
        <div class="te-bundle-summary" id="wkSummary">
          <span>${esc(data.type_code)} ${s.documents}건:</span> ${statusSummary(s.status_counts, s.correcting_count) || '<span class="te-hint">문서 없음</span>'}
          <span style="flex:1"></span><span>내 결재 대기 <b>${s.my_pending}</b></span>
        </div>
        <div class="te-bundle-actions">
          ${assign ? btn('wkInspector', '점검자 지정', n.inspector) : `<button class="btn btn-secondary btn-sm" id="wkInspector" disabled title="${esc(T.INSPECTOR_WHY)}">점검자 지정 (${n.inspector})</button>`} ${btn('wkSubmit', '선택 상신', n.submit)} ${btn('wkApprove', '선택 승인', n.approve)} ${btn('wkSkip', '작성 안 함', n.skip)}
          <span class="te-hint" id="wkPicked">선택 ${picked.length}건${over ? ` — <span class="te-error-text">한 번에 ${max}건까지</span>` : ''}</span>
          <span style="flex:1"></span>
          ${WEEK_PRINT_TYPES.includes(data.type_code)
            ? `<button class="btn btn-secondary btn-sm" id="wkPrint" ${this.week.start > today() ? 'disabled title="아직 오지 않은 주입니다"' : 'title="이 주의 점검표(주말 문서가 있으면 그 요일 칸 포함)"'}>주 출력</button>`
            : '<button class="btn btn-secondary btn-sm" disabled title="주 출력은 다음 단계(P12)">주 출력 <span class="te-hint">(P12)</span></button>'}
        </div>
        ${assign ? '' : `<div class="te-perm-note" id="wkInspectorWhy">${esc(T.INSPECTOR_WHY)} ${T.roleLink()}</div>`}
        <div class="te-table-wrap"><table class="data-table" id="wkTable">
          <thead><tr><th class="te-check-col"><input type="checkbox" id="wkAll" ${rows.length && picked.length === rows.length ? 'checked' : ''} ${rows.length ? '' : 'disabled'} title="문서 있는 날 전체"></th>
            <th>날짜</th><th>문서</th><th>상태</th><th>점검자</th><th>점검 결과</th><th>판정</th><th>결재</th></tr></thead>
          <tbody>${data.days.map(dayRow).join('')}</tbody>
        </table></div>
        ${data.weekend.length ? `<div class="te-bundle-missing" id="wkWeekend">주말 문서 ${data.weekend.length}건 별도: ${data.weekend.map((x) => `<a href="#" class="te-lot-link" data-open-doc="${x.document.document_id}">${mmdd(x.work_date)} (${WEEKDAY[x.weekday % 7]}) #${x.document.document_id}</a>`).join(', ')}</div>` : ''}`;
      const $ = (sel) => body.querySelector(sel);
      $('#wkPrint')?.addEventListener('click', () => window.open(`/print/?kind=weekly&type=${encodeURIComponent(data.type_code)}&date=${this.week.start}`, '_blank'));
      body.querySelectorAll('[data-pick]').forEach((c) => c.addEventListener('change', () => {
        const id = Number(c.dataset.pick);
        if (c.checked) selected.add(id); else selected.delete(id);
        this.renderWeek();
      }));
      $('#wkAll').addEventListener('change', (e) => {
        rows.forEach((x) => { if (e.target.checked) selected.add(x.document_id); else selected.delete(x.document_id); });
        this.renderWeek();
      });
      body.querySelectorAll('[data-open-doc]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); this.openFromWeek(Number(a.dataset.openDoc)); }));
      const B = window.TempEntryApproval.batch;
      const after = {
        onDone: () => { this.week.selected = new Set(); this.showWeek(this.week.type, this.week.start, this.week.origin); },
        openDoc: (id) => { this.week.selected = new Set(); this.openFromWeek(id); },
      };
      $('#wkApprove').addEventListener('click', () => B.openApprove(picked, { origin: 'bundle', ...after }));
      $('#wkSubmit').addEventListener('click', () => B.openSubmit(picked, data.approval_line, after));
      $('#wkInspector').addEventListener('click', () => B.guardOpen(async () => this.openInspector(picked, after, max)));
      $('#wkSkip').addEventListener('click', () => B.guardOpen(async () => this.openSkip(picked, { ...after, title: `${data.type_code} ${picked.filter((x) => x.status === 'draft').length}건`, max })));
    },

    // ================================================= DOC-SC-13 작성 안 함 모달 (P8, F27 — 한 건도 같은 API)
    // rows: [{document_id, version, status, lot(표시 이름)}]. 작성중만 대상, 나머지는 제외 목록.
    openSkip(rows, { onDone, openDoc, title, max = 50, single = false }) {
      const B = window.TempEntryApproval.batch;
      // r13(DOC-SC-10): 작성 권한 없는 문서(can_write false)는 "⚠ 작성 권한 없음"으로 빼서 보임 — 한 건(상세)은 버튼에서 이미 막음
      const targets = rows.filter((x) => x.status === 'draft' && x.can_write !== false);
      const excluded = rows.filter((x) => x.status !== 'draft').map((row) => ({ row, why: `(${T.STATUS[row.status]?.label || row.status} — 작성중만 가능)` }))
        .concat(rows.filter((x) => x.status === 'draft' && x.can_write === false).map((row) => ({ row, why: '(⚠ 작성 권한 없음)' })));
      const m = B.modal(`작성 안 함 — ${title}`);
      const st = { reason: '', busy: false, error: '' };
      const render = () => {
        const text = st.reason.trim();
        const tooLong = st.reason.length > 200;
        m.body.innerHTML = `
          ${st.error}
          ${single ? '' : `<ul class="te-target-list" id="skTargets">${targets.map((x) => `<li data-target="${x.document_id}">${B.rowName(x)}</li>`).join('') || '<li class="te-hint">작성중인 문서가 없습니다.</li>'}</ul>${B.excludedHtml(excluded)}${B.overLimit(targets.length, max)}`}
          <label class="form-label">사유 *</label>
          <div class="te-quick" id="skQuick">${['휴무', '작업 없음'].map((q) => `<button class="btn btn-secondary btn-sm" data-quick="${q}">${q}</button>`).join('')}</div>
          <input class="form-control ${tooLong ? 'te-field-error' : ''}" id="skReason" maxlength="220" placeholder="직접 입력" value="${esc(st.reason)}">
          <div class="te-counter" id="skCount">${st.reason.length}/200</div>
          <p class="te-status-note" style="margin-top:.5rem">결재·미작성 집계에서 빠지고, 출력하면 그 날은 "작성 안 함"으로 나옵니다. [되돌리기]로 다시 작성할 수 있습니다.</p>`;
        const can = api.staffId && targets.length && targets.length <= max && text && !tooLong && !st.busy;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="skCancel">취소</button>
          <button class="btn btn-primary" id="skGo" ${can ? '' : 'disabled'}>${st.busy ? '처리 중…' : (single ? '작성 안 함' : `${targets.length}건 작성 안 함`)}</button>`;
        const input = m.body.querySelector('#skReason');
        input.addEventListener('input', (e) => {
          st.reason = e.target.value;
          m.body.querySelector('#skCount').textContent = `${st.reason.length}/200`;
          input.classList.toggle('te-field-error', st.reason.length > 200);
          m.footer.querySelector('#skGo').disabled = !(api.staffId && targets.length && targets.length <= max && st.reason.trim() && st.reason.length <= 200);
        });
        m.body.querySelectorAll('[data-quick]').forEach((b) => b.addEventListener('click', () => { st.reason = b.dataset.quick; render(); }));
        m.footer.querySelector('#skCancel').addEventListener('click', m.close);
        m.footer.querySelector('#skGo').addEventListener('click', go);
      };
      const go = async () => {
        st.busy = true;
        st.error = '';
        render();
        const res = await api.post('documents/batch-skip', { items: targets.map((x) => ({ document_id: x.document_id, expected_version: x.version })), reason: st.reason });
        st.busy = false;
        if (res.ok && single) {
          const line = res.data.results[0];
          if (line.ok) { m.close(); T.toast('작성 안 함으로 바꿨습니다.', 'success'); onDone && onDone(); return; }
          st.error = `<div class="te-error-box" id="skError"><strong>[${esc(line.error.code)}] ${esc(B.failureText('skip', line.error))}</strong></div>`;
          render();
          return;
        }
        if (res.ok) { B.showResult(m, 'skip', res.data, targets, { onDone, openDoc }); return; }
        const details = (res.data && res.data.details) || [];
        st.error = `<div class="te-error-box" id="skError"><strong>${esc(T.errorText(res))}</strong> 아무것도 처리하지 않았습니다.${details.length ? `<ul>${details.map((e) => `<li>${esc(e.message)}</li>`).join('')}</ul>` : ''}</div>`;
        T.toast(T.errorText(res), 'error');
        render();
      };
      render();
    },

    // ================================================= DOC-SC-11 점검자 일괄 지정 (P7, 컷 ①)
    openInspector(rows, after, max = 50) {
      const B = window.TempEntryApproval.batch;
      const targets = rows.filter((x) => EDITABLE.includes(x.status));
      const why = (x) => (x.status === 'completed' ? '작성완료 — 수정하려면 작성 재개' : '결재 중이거나 승인됨');
      const excluded = rows.filter((x) => !EDITABLE.includes(x.status)).map((row) => ({ row, why: `(${why(row)})` }));
      const m = B.modal(`점검자 지정 · ${targets.length}건`);
      const state = { inspector: '', busy: false, error: '' };
      const render = () => {
        const options = T.staffOptions(state.inspector, { blank: '선택' });
        m.body.innerHTML = `
          <p class="te-hint">기본정보의 점검자를 한 번에 바꿉니다(문서마다 저장, 버전 확인). 이미 같은 점검자인 문서는 "변화 없음"입니다.</p>
          ${state.error}
          <ul class="te-target-list" id="bxTargets">${targets.map((x) => `<li data-target="${x.document_id}">${B.rowName(x)} <span class="te-hint">(지금: ${esc(T.person(x.inspector_id))})</span></li>`).join('')
            || '<li class="te-hint">수정 가능한(작성중·반려·정정 중) 문서가 없습니다.</li>'}</ul>
          ${B.excludedHtml(excluded)}
          ${B.overLimit(targets.length, max)}
          <div class="form-group" style="margin-top:.75rem"><label class="form-label">점검자 *</label><select class="form-control" id="bxInspector">${options}</select></div>`;
        const can = api.staffId && targets.length && targets.length <= max && state.inspector && !state.busy;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="bxCancel">취소</button>
          <button class="btn btn-primary" id="bxGo" ${can ? '' : 'disabled'}>${state.busy ? '처리 중…' : `${targets.length}건 지정`}</button>`;
        m.body.querySelector('#bxInspector').addEventListener('change', (e) => { state.inspector = e.target.value; render(); });
        m.footer.querySelector('#bxCancel').addEventListener('click', m.close);
        m.footer.querySelector('#bxGo').addEventListener('click', go);
      };
      const go = async () => {
        state.busy = true;
        state.error = '';
        render();
        const inspectorId = Number(state.inspector);
        const res = await api.post('documents/batch-inspector', {
          items: targets.map((x) => ({ document_id: x.document_id, expected_version: x.version })), inspector_id: inspectorId,
        });
        state.busy = false;
        if (res.ok) { B.showResult(m, 'inspector', res.data, targets, { ...after, extra: { inspectorId } }); return; }
        state.error = `<div class="te-error-box" id="bxError"><strong>${esc(T.errorText(res))}</strong> 아무것도 처리하지 않았습니다.</div>`;
        T.toast(T.errorText(res), 'error');
        render();
      };
      render();
    },

    // ================================================= DOC-SC-02 양식 선택
    async showPicker() {
      // 작성 요구 양식은 작성 요구로만 생긴다(P4-S1-Q1). 단 주기 양식은 날짜를 골라 직접 만들 수 있다(P9 D-113 — 규칙 파일 양식, 꺼진 규칙도)
      const [all, rulesRes] = await Promise.all([this.loadTemplates(), api.get('periodic-rules')]);
      const templates = all.filter((t) => !t.requirement_only);
      const rules = rulesRes.ok ? rulesRes.data.rules : [];
      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar('새 문서 › 양식 선택', '활성 양식 중 유형별 최신 버전만 표시됩니다.')}
          <h3 class="te-sub">일반 양식</h3>
          ${templates.length ? `<div class="te-cards">${templates.map((t) => `
            <div class="card">
              <div class="card-title">${esc(t.name)}</div>
              <div class="te-card-meta">${esc(t.type_code)} · v${t.version}</div>
              <div class="te-hint">${t.sections.map((s) => `${esc(s.label)}${s.repeat ? '(반복)' : ''}`).join(' · ')}</div>
              <div class="te-actions">${!api.staffId || T.canWriteForm(api.staffId, t.type_code)
                ? `<button class="btn btn-primary btn-sm" data-template="${t.template_id}">선택</button>`
                : `<button class="btn btn-secondary btn-sm" data-template="${t.template_id}" disabled title="${esc(T.WRITE_WHY)}">선택</button> <span class="te-hint">작성 권한 없음</span>`}</div>
            </div>`).join('')}</div>`
          : '<div class="te-empty">사용 가능한 양식이 없습니다 (개발용 시드 데이터를 넣으세요).</div>'}
          <h3 class="te-sub">주기 양식 (날짜마다 1건)</h3>
          ${rules.length ? `<div class="te-table-wrap"><table class="data-table" id="tePeriodicPick">
            <tbody>${rules.map((x) => `<tr data-periodic-row="${esc(x.type_code)}">
              <td class="mono">${esc(x.type_code)}</td><td>${esc(x.name || '(사용 중인 양식 없음)')}</td>
              <td class="te-hint">${esc(periodicRuleText(x))}${x.enabled ? '' : ' · 자동 생성 꺼짐'}</td>
              <td><button class="btn btn-primary btn-sm" data-periodic="${esc(x.type_code)}" data-name="${esc(x.name || x.type_code)}" data-cadence="${esc(x.cadence)}">선택</button></td>
            </tr>`).join('')}</tbody></table></div>`
          : `<div class="te-empty" id="tePeriodicNone">${rulesRes.ok ? '주기 양식이 없습니다.' : esc(T.errorText(rulesRes))}</div>`}
          <p class="te-hint" id="teReqNote" style="margin-top:1rem">시험성적서·원산지·육안검사·CCP 일지는 입고·생산 시작 때 자동으로 만들어집니다.</p>
          <div class="te-actions"><button class="btn btn-secondary" id="btnCancel">취소</button></div>
        </div>`;
      this.rerenderTopBar(() => this.showPicker());
      this.root.querySelector('#btnCancel').addEventListener('click', () => this.showList());
      this.root.querySelectorAll('button[data-template]').forEach((b) =>
        b.addEventListener('click', () => this.openForm({ templateId: Number(b.dataset.template) })));
      this.root.querySelectorAll('button[data-periodic]').forEach((b) =>
        b.addEventListener('click', () => this.openPeriodicDate({ type_code: b.dataset.periodic, name: b.dataset.name, cadence: b.dataset.cadence })));
    },

    // ================================================= DOC-SC-14 주기 문서 날짜 선택 (P9, REQ-A06)
    // 미래·주말도 됨(특근일). 그날(D11은 그 주) 문서가 있으면 그 문서를, 없으면 만들어 작성 폼으로
    openPeriodicDate(rule) {
      const wrap = document.createElement('div');
      wrap.className = 'te-modal-wrap';
      wrap.innerHTML = `
        <div class="te-modal" role="dialog" aria-modal="true" id="tePeriodicDate">
          <div class="modal-header"><div class="modal-title">새 문서 › ${esc(rule.type_code)} ${esc(rule.name)}</div></div>
          <div class="te-modal-body">
            <label class="form-label">날짜</label>
            <div class="te-prd-day"><input type="date" class="form-control" id="pdDay" value="${seoulDay()}"> <span id="pdDow"></span></div>
            <p class="te-hint">날짜마다 문서가 1건입니다. 그날 문서가 이미 있으면 그 문서를 엽니다.</p>
            <p class="te-hint">작성하지 않는 날은 [작성 안 함]을 쓰세요. 날짜를 잘못 골랐으면 작성중·상신 전에 [삭제]할 수 있습니다.</p>
            <div class="te-error-text" id="pdError"></div>
          </div>
          <div class="te-modal-footer"><button class="btn btn-secondary" id="pdCancel">취소</button><button class="btn btn-primary" id="pdOpen">열기</button></div>
        </div>`;
      document.body.appendChild(wrap);
      const $ = (sel) => wrap.querySelector(sel);
      const close = () => wrap.remove();
      const showDow = () => {
        const day = $('#pdDay').value;
        if (!day) { $('#pdDow').textContent = ''; return; }
        const monday = shiftDay(day, -((new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7));
        $('#pdDow').textContent = rule.cadence === 'weekly' ? `(${dow(day)}) → ${monday.slice(5)}(월) 주 문서` : `(${dow(day)})`;
      };
      showDow();
      $('#pdDay').addEventListener('input', () => { $('#pdError').textContent = ''; showDow(); });
      wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
      $('#pdCancel').addEventListener('click', close);
      $('#pdOpen').addEventListener('click', async () => {
        const day = $('#pdDay').value;
        if (!day) { $('#pdError').textContent = '날짜를 고르세요.'; return; }
        const btn = $('#pdOpen');
        btn.disabled = true;  // 실행 중 두 번 누름 막기
        try {
          const r = await api.post('periodic-documents', { type_code: rule.type_code, date: day });
          if (!r.ok) { $('#pdError').textContent = periodicOpenError(r); return; }
          close();
          const id = r.data.document_id;
          if (r.data.result === 'existing') {
            T.toast(`${r.data.work_date.slice(5)} 문서가 이미 있습니다(#${id} ${T.STATUS[r.data.status]?.label || r.data.status}).`, 'info');
            this.showDetail(id);
            return;
          }
          const d = await api.get(`documents/${id}`);
          if (!d.ok) { T.toast(T.errorText(d), 'error'); this.showDetail(id); return; }
          this.openForm({ document: d.data });
        } finally { btn.disabled = false; }
      });
      $('#pdDay').focus();
    },

    // ================================================= DOC-SC-03 작성/수정 폼
    async openForm({ templateId, document, pending, problems }) {
      const tid = document ? document.template.template_id : templateId;
      const r = await api.get(`templates/${tid}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const schema = r.data.schema;
      let uid = 0;
      const rows = [];
      const sectionByKey = Object.fromEntries(schema.sections.map((s) => [s.key, s]));
      const hinted = [];
      if (document) {
        document.sections.forEach((s) => {
          const row = {
            uid: ++uid, key: s.section_def, sectionId: s.section_id, rowNo: s.row_no,
            values: { ...s.values }, original: { ...s.values }, deleted: false, hints: s.hints || {},
          };
          // hint(FR-28): 빈 칸을 계산 값으로 채운다. 저장 전까지는 "변경"으로 표시된다.
          Object.entries(row.hints).forEach(([k, v]) => {
            if (row.values[k] === undefined || row.values[k] === null || row.values[k] === '') { row.values[k] = v; hinted.push(`${row.uid}.${k}`); }
          });
          rows.push(row);
        });
      } else {
        schema.sections.forEach((s) => {
          if (!s.repeat) rows.push({ uid: ++uid, key: s.key, sectionId: null, values: {}, original: null, deleted: false, hints: {} });
        });
      }
      // P8: date_window 날짜(D11 점검일)가 비어 있으면 기본 = 작업일(월요일, p8-s0 F7) — 저장 전까지 "변경"
      if (document) {
        rows.filter((row) => !sectionByKey[row.key]?.repeat).forEach((row) => {
          sectionByKey[row.key].fields.filter((fd) => fd.date_window && !row.values[fd.key]).forEach((fd) => {
            row.values[fd.key] = shiftDay(document.work_date, fd.date_window.from);
            hinted.push(`${row.uid}.${fd.key}`);
          });
        });
      }
      // P8 F29: 최근 값 제안(datalist)
      const recent = {};
      await Promise.all((RECENT_FIELDS[r.data.type_code] || []).map(async (key) => {
        const res = await api.get(`documents/recent-values?type_code=${encodeURIComponent(r.data.type_code)}&field=${key}`);
        recent[key] = res.ok ? res.data.items : [];
      }));
      const basic = document
        ? { subject: document.subject || '', work_date: document.work_date, due_at: document.due_at ? document.due_at.slice(0, 16) : '' }
        : { subject: '', work_date: today(0), due_at: '' };  // P14 Q3 a: 담당자(assignee_id)는 고르지 않음 — 양식 담당자
      this.form = {
        mode: document ? 'edit' : 'create', template: r.data, schema, sectionByKey, document,
        requirement: !!(document && document.record_key),
        rows, basic, originalBasic: { ...basic }, nextUid: uid, errors: {}, errorList: [],
        pending: pending || [], hinted: new Set(hinted), recent,
      };
      if (!document) schema.sections.filter((s) => s.repeat && !s.system_rows).forEach((s) => this.addRow(s.key, false));
      if (problems) this.applyErrors({ code: 'COMPLETION_INCOMPLETE', message: '작성완료할 수 없습니다. 빠진 항목을 채우세요.', details: problems }, {}, true);
      else this.renderForm();
    },

    addRow(key, redraw = true) {
      const f = this.form;
      const values = {};
      // CCP-3P 제품 통과 요약: 품명 기본값 = 기본정보의 품명(배치 품목, D-060 Q2)
      const section = f.sectionByKey[key];
      const info = f.rows.find((r) => r.key === 'info');
      if (section.fields.some((fd) => fd.key === 'item_name' && !fd.readonly) && info && info.values.item_name) values.item_name = info.values.item_name;
      f.rows.push({ uid: ++f.nextUid, key, sectionId: null, values, original: null, deleted: false, hints: {} });
      if (redraw) this.renderForm();
    },

    fieldInput(field, value, row) {
      const name = `data-row="${row.uid}" data-field="${field.key}"`;
      const v = value === undefined || value === null ? '' : value;
      if (field.readonly) return `<span class="te-ro" title="자동 입력(수정 불가)">${this.display(field, value)}</span>`;
      if (field.computed) {
        const section = this.form.sectionByKey[row.key];
        return `<span data-computed="${row.uid}.${field.key}">${this.display(field, withComputed(section, row.values)[field.key])}</span>`;
      }
      const staffOptions = T.staffOptions(v);
      const hinted = this.form.hinted.has(`${row.uid}.${field.key}`);
      const hintMark = hinted ? `<div class="te-hint">${field.date_window ? '기본값(작업일) — 저장하면 확정' : '자동 제안(같은 LOT 성적서)'}</div>` : '';
      switch (field.type) {
        case 'number':
          if (field.display === 'hm') {
            const h = v === '' ? '' : Math.floor(v / 60);
            const m = v === '' ? '' : v % 60;
            return `<span class="te-hm"><input type="number" min="0" class="form-control" ${name} data-part="h" value="${h}">시간<input type="number" min="0" max="59" class="form-control" ${name} data-part="m" value="${m}">분</span>`;
          }
          return `<input type="number" step="any" class="form-control" ${name} value="${esc(v)}">`;
        case 'time': return `<input type="time" class="form-control" ${name} value="${esc(v)}">`;
        case 'date': {
          // P8 date_window(VR-P8-02): 작업일 + from ~ + to 안에서만 고르게
          const w = field.date_window;
          const range = w ? `min="${shiftDay(this.form.basic.work_date, w.from)}" max="${shiftDay(this.form.basic.work_date, w.to)}"` : '';
          return `<input type="date" class="form-control" ${name} value="${esc(v)}" ${range}>${hintMark}`;
        }
        case 'datetime': {
          // 날짜 기본값 = 작업일(D-051 F11). 시각을 넣어야 값이 생긴다.
          const date = v ? v.slice(0, 10) : this.form.basic.work_date;
          const time = v ? v.slice(11, 16) : '';
          return `<span class="te-dt"><input type="date" class="form-control" ${name} data-part="date" value="${esc(date)}"><input type="time" class="form-control" ${name} data-part="time" value="${esc(time)}"></span>`;
        }
        case 'bool': return `<input type="checkbox" ${name} ${v === true ? 'checked' : ''}>`;
        case 'staff':
          // r13 ROLE-R08: 기본정보 점검자는 담당자·HACCP팀장만 바꿈 — 아니면 읽기만(+ 이유)
          if (field.key === 'inspector' && row.key === 'info' && !T.canAssignInspector(api.staffId, this.form.template.type_code)) {
            return `<span class="te-ro" data-inspector-ro title="${esc(T.INSPECTOR_WHY)}">${v === '' ? '<span class="te-hint">-</span>' : T.personHtml(v)}</span><div class="te-hint">${esc(T.INSPECTOR_WHY)}</div>`;
          }
          return `<select class="form-control" ${name}>${staffOptions}</select>`;
        case 'select': return `<select class="form-control" ${name}><option value="">-</option>${field.options.map((o) => `<option value="${esc(o)}" ${o === v ? 'selected' : ''}>${esc(optionLabel(field, o))}</option>`).join('')}</select>${hintMark}`;
        default: {
          const recent = this.form.recent && this.form.recent[field.key];
          const list = recent ? ` list="dl-${row.uid}-${field.key}"` : '';
          const options = recent ? `<datalist id="dl-${row.uid}-${field.key}">${recent.map((x) => `<option value="${esc(x)}">`).join('')}</datalist>${recent.length ? `<div class="te-hint">최근: ${recent.slice(0, 5).map(esc).join(', ')}</div>` : ''}` : '';
          return `<input type="text" class="form-control" ${name} value="${esc(v)}" ${field.max_length ? `maxlength="${field.max_length}"` : ''}${list}>${options}`;
        }
      }
    },

    readInput(el, field) {
      if (field.type === 'bool') return el.checked ? true : undefined;
      const scope = el.closest('td, .form-group') || el.parentElement;
      const part = (p) => scope.querySelector(`[data-field="${field.key}"][data-part="${p}"]`);
      if (field.type === 'datetime') {
        const date = part('date').value;
        const time = part('time').value;
        return date && time ? `${date}T${time}` : undefined;
      }
      if (field.display === 'hm') {
        const h = part('h').value;
        const m = part('m').value;
        if (h === '' && m === '') return undefined;
        return Number(h || 0) * 60 + Number(m || 0);
      }
      const raw = el.value;
      if (raw === '') return undefined;
      if (field.type === 'number') { const n = Number(raw); return Number.isNaN(n) ? raw : n; }
      if (field.type === 'staff') return Number(raw);
      return raw;
    },

    // P1 양식(한계기준 limit만 있는 섹션)의 화면 판정. P4 양식은 computed 필드가 판정이다.
    judge(section, values) {
      if (hasComputed(section)) return isNonconforming(section, values) ? 'ng' : null;
      const limited = section.fields.filter((fd) => fd.limit);
      if (!limited.length) return isNonconforming(section, values) ? 'ng' : null;
      let missing = false;
      for (const fd of limited) {
        const v = values[fd.key];
        if (typeof v !== 'number') { missing = true; continue; }
        if ((fd.limit.min !== undefined && v < fd.limit.min) || (fd.limit.max !== undefined && v > fd.limit.max)) return 'ng';
      }
      return missing ? null : 'ok';
    },

    judgeCell(section, values) {
      const j = this.judge(section, values);
      if (j === 'ok') return '<span class="te-judge-ok">적합</span>';
      if (j === 'ng') return '<span class="te-judge-ng">⚠ 부적합</span>';
      return '<span class="te-hint">-</span>';
    },
    legacyJudge: (s) => !hasComputed(s) && s.fields.some((fd) => fd.limit),

    rowState(row) {
      if (row.deleted) return 'deleted';
      if (!row.sectionId) return 'new';
      return Object.keys(this.rowPatch(row)).length ? 'changed' : '';
    },

    rowPatch(row) {
      const patch = {};
      const section = this.form.sectionByKey[row.key];
      const system = new Set(section.fields.filter(isSystem).map((fd) => fd.key));
      const keys = new Set([...Object.keys(row.original || {}), ...Object.keys(row.values)]);
      keys.forEach((k) => {
        if (system.has(k)) return; // 자동 값·판정은 보내지 않는다(VR-16)
        const a = (row.original || {})[k];
        const b = row.values[k];
        if (JSON.stringify(a) !== JSON.stringify(b)) patch[k] = b === undefined ? null : b;
      });
      return patch;
    },

    userValues(row) {
      const section = this.form.sectionByKey[row.key];
      const system = new Set(section.fields.filter(isSystem).map((fd) => fd.key));
      return Object.fromEntries(Object.entries(row.values).filter(([k]) => !system.has(k)));
    },

    basicChanges() {
      const f = this.form;
      const out = {};
      Object.keys(f.basic).forEach((k) => {
        if (f.requirement && (k === 'work_date' || k === 'subject')) return;
        if (f.basic[k] !== f.originalBasic[k]) out[k] = f.basic[k];
      });
      return out;
    },

    isDirty() {
      const f = this.form;
      if (f.mode === 'create') return true;
      return Object.keys(this.basicChanges()).length > 0 || f.rows.some((r) => this.rowState(r));
    },

    errorFor(rowUid, key) {
      const msg = this.form.errors[`${rowUid}.${key}`];
      return msg ? `<div class="te-error-text">${esc(msg)}</div>` : '';
    },

    // ================================================= P8 점검표 섹션 (DOC-SC-03·04, p8-s1-screens 2·3장)
    // 주기·관리 칸은 같은 값이 이어지면 〃. "미리" = N1이 채운 값(prefilled)을 아직 안 바꾼 칸(문서 version 1일 때만 옴)
    checkRows(s, values, cell) {
      let prev = {};
      return s.fields.map((fd) => {
        const same = (k) => fd[k] && fd[k] === prev[k];
        const line = `<tr data-check="${fd.key}" class="${values[fd.key] === 'X' ? 'te-check-row-ng' : ''}">
          <td class="te-check-cad">${same('cadence') ? '<span class="te-ditto">〃</span>' : esc(fd.cadence || '')}</td>
          <td class="te-check-grp">${same('cadence') && same('group') ? '<span class="te-ditto">〃</span>' : esc(fd.group || '')}</td>
          <td>${esc(fd.label)}${fd.required ? ' *' : ''}</td>
          <td class="te-nowrap">${cell(fd)}</td></tr>`;
        prev = fd;
        return line;
      }).join('');
    },

    checklistFormHtml(s, row, sectionErr) {
      const f = this.form;
      const pre = new Set((f.document && f.document.prefilled) || []);
      const daily = s.fields.filter(isDaily);
      const cell = (fd) => {
        const v = row.values[fd.key];
        if (!isResult(fd)) return `${fd.type === 'date' ? '<span class="te-hint">실시일</span> ' : ''}${this.fieldInput(fd, v, row)}${this.errorFor(row.uid, fd.key)}`;
        const untouched = v !== undefined && v === (row.original || {})[fd.key];
        return `<span class="te-ox" data-ox="${row.uid}.${fd.key}">${fd.options.map((o) => `<button type="button" data-v="${esc(o)}" class="${v === o ? 'te-on' : ''}">${esc(optionLabel(fd, o))}</button>`).join('')}</span>
          ${pre.has(`${s.key}.${fd.key}`) && untouched ? '<span class="te-prefilled" title="새 문서에 미리 채운 값 — 바꿀 수 있음">미리</span>' : ''}
          ${v === 'X' ? '<span class="te-judge-ng" title="저장 뒤 상세에서 이탈·개선조치를 적으세요">⚠</span>' : ''}${this.errorFor(row.uid, fd.key)}`;
      };
      // C3 S6(ISS-033): 점검표는 섹션 전체 강조 대신 X 줄만 강조(p8-s1 "X 줄 강조") — 섹션째 칠하면 X 줄이 묻힌다
      const ng = isNonconforming(s, row.values);
      return `<div class="te-section te-check-section" id="teChecklist">
        <div class="te-section-head"><span class="te-section-title">${esc(s.label)} <span class="te-hint">${s.fields.filter(isResult).length}항목 · 다시 누르면 빈칸</span></span>
          ${daily.length ? `<button class="btn btn-secondary btn-sm" data-all-o="${row.uid}" id="teAllO" title="매일 항목 ${daily.length}개 중 빈칸만 O로(이미 고른 값은 그대로)">매일 항목 모두 O</button>` : ''}</div>${sectionErr}
        ${ng ? '<div class="te-error-text">X(불량·부적합)가 있습니다 — 저장한 뒤 상세 화면에서 이탈·개선조치를 1건 이상 적어야 작성완료할 수 있습니다.</div>' : ''}
        <div class="te-table-wrap"><table class="data-table te-check-table">
          <thead><tr><th>주기</th><th>관리</th><th>검증 내용</th><th>결과</th></tr></thead>
          <tbody>${this.checkRows(s, row.values, cell)}</tbody></table></div></div>`;
    },

    checklistDetailHtml(s, d, detail) {
      const v = ((d.sections.find((x) => x.section_def === s.key) || {}).values) || {};
      const canDev = detail && api.staffId && d.status !== 'skipped';
      const cell = (fd) => {
        const value = v[fd.key];
        if (!isResult(fd)) return value ? `<span class="te-hint">실시일</span> ${esc(value)}` : '<span class="te-hint">-</span>';
        if (!value) return '<span class="te-hint">빈칸</span>';
        const text = esc(optionLabel(fd, value));
        if (value !== 'X') return value === 'NA' ? `<span class="te-hint">${text}</span>` : text;
        return `<span class="te-judge-ng">⚠ ${text}</span>${canDev ? ` <button class="btn btn-secondary btn-sm te-dev-add" data-dev-for="" data-dev-text="${esc(`${fd.label} — 불량`)}">개선조치 추가</button>` : ''}`;
      };
      const ng = isNonconforming(s, v);  // 머리 ⚠ 부적합은 유지, 강조는 X 줄만(ISS-033)
      return `<div class="te-section te-check-section"><div class="te-section-title">${esc(s.label)}${ng ? ' <span class="te-judge-ng">⚠ 부적합</span>' : ''}</div>
        <div class="te-table-wrap"><table class="data-table te-check-table" id="teCheckView">
          <thead><tr><th>주기</th><th>관리</th><th>검증 내용</th><th>결과</th></tr></thead>
          <tbody>${this.checkRows(s, v, cell)}</tbody></table></div></div>`;
    },

    guideHtml(schema) {
      if (!schema.guide || !schema.guide.length) return '';
      return `<details class="te-guide" id="teGuide"><summary>고정 안내 (관리기준) 펼치기</summary>
        ${schema.guide.map((g) => `<div class="te-section-title">${esc(g.title)}</div>
          <table class="data-table"><tbody>${g.rows.map(([k, v]) => `<tr><th class="te-nowrap">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</tbody></table>`).join('')}
      </details>`;
    },

    renderForm() {
      const f = this.form;
      const d = f.document;
      const title = f.mode === 'create' ? `새 문서 › ${f.template.name} v${f.template.version}` : `문서 #${d.document_id} 수정 › ${f.template.name} v${f.template.version}`;
      const changed = this.basicChanges();
      const cls = (k) => (f.mode === 'edit' && k in changed ? 'te-field-changed' : '') + (f.errors[`basic.${k}`] ? ' te-field-error' : '');
      const basicErr = (k) => (f.errors[`basic.${k}`] ? `<div class="te-error-text">${esc(f.errors[`basic.${k}`])}</div>` : '');
      const future = f.basic.work_date > today(0) ? '<div class="te-hint">미래 날짜입니다(작성 지시용).</div>' : '';
      const author = f.mode === 'create' ? esc(api.staffId ? `${T.person(api.staffId)} (자동)` : '현재 사용자 미선택') : T.authorHtml(d);
      const owners = T.ownersOf(f.template.type_code);
      // r13: 작성(R07)은 양식 역할 또는 이 문서 점검자 — 화면에서 사용자를 바꾸면 다시 계산(서버가 다시 검사)
      const infoRow = f.rows.find((r) => r.key === 'info');
      const canWrite = T.canWriteForm(api.staffId, f.template.type_code, f.mode === 'edit' && infoRow ? (infoRow.original || {}).inspector : null);
      f.canWrite = canWrite;

      const sectionsHtml = f.schema.sections.map((s) => {
        const rows = f.rows.filter((r) => r.key === s.key);
        const sectionErr = f.errors[`section.${s.key}`] ? `<div class="te-error-text" data-error-section="${s.key}">${esc(f.errors[`section.${s.key}`])}</div>` : '';
        if (isChecklist(s)) return this.checklistFormHtml(s, rows[0], sectionErr);
        if (!s.repeat) {
          const row = rows[0];
          const ng = row && isNonconforming(s, row.values) ? ' te-section-ng' : '';
          return `<div class="te-section${ng}" ${s.nonconforming && row ? `data-ng-section="${row.uid}"` : ''}><div class="te-section-head"><span class="te-section-title">${esc(s.label)}</span><span class="te-hint">행 1개</span></div>${sectionErr}
            <div class="te-grid">${s.fields.map((fd) => {
              const focus = verdictFocus(f.template.type_code, fd);
              return `
              <div class="form-group${focus ? ' te-verdict-field' : ''}"><label class="form-label">${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</label>
                ${this.fieldInput(fd, row.values[fd.key], row)}${this.errorFor(row.uid, fd.key)}
                ${focus ? `<div class="te-verdict-hint" data-verdict-hint="${row.uid}" ${verdictWarn(s, row.values) ? '' : 'hidden'}>${esc(VERDICT_HINT)}</div>` : ''}</div>`;
            }).join('')}</div></div>`;
        }
        const legacy = this.legacyJudge(s);
        const limits = s.fields.filter((fd) => fd.limit).map((fd) => `${fd.label} ${fd.limit.min !== undefined ? `${fd.limit.min}${fd.unit || ''} 이상` : ''}${fd.limit.max !== undefined ? ` ${fd.limit.max}${fd.unit || ''} 이하` : ''}`).join(', ');
        const canAdd = !s.system_rows;
        // 측정자 = 행 기록자(recorded_by). 설계 순서(판정 → 측정자 → 비고)대로 판정 열 바로 뒤에 둔다
        const recorder = hasComputed(s);
        const recorderCell = (row) => `<td class="te-hint">${row.sectionId ? T.personHtml((d.sections.find((x) => x.section_id === row.sectionId) || {}).recorded_by) : T.personHtml(api.staffId || null)}</td>`;
        const afterField = (fd, html) => (recorder && fd.computed ? html : '');
        return `<div class="te-section">
          <div class="te-section-head"><span class="te-section-title">${esc(s.label)} <span class="te-hint">반복${s.max_rows ? ` · 최대 ${s.max_rows}행` : ''}${s.min_rows ? ` · 최소 ${s.min_rows}행(작성완료 때)` : ''}${limits ? ` · 한계기준: ${esc(limits)}` : ''}${s.system_rows ? ' · 행은 입고 때 자동으로 추가됩니다' : ''}</span></span>
            ${canAdd ? `<button class="btn btn-secondary btn-sm" data-add="${s.key}">+ 행 추가</button>` : ''}</div>${sectionErr}
          <div class="te-table-wrap"><table class="data-table te-rows">
            <thead><tr><th>#</th>${s.fields.map((fd) => `<th class="${fd.readonly ? 'te-ro-head' : ''}">${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>${afterField(fd, '<th>측정자</th>')}`).join('')}${legacy ? '<th>판정</th>' : ''}${canAdd ? '<th></th>' : ''}</tr></thead>
            <tbody>${rows.length ? rows.map((row, i) => `
              <tr class="te-row-${this.rowState(row) || 'same'}${isNonconforming(s, row.values) ? ' te-row-ng' : ''}" data-tr="${row.uid}">
                <td>${i + 1}</td>
                ${s.fields.map((fd) => `<td class="${fd.readonly ? 'te-ro-cell' : ''}">${this.fieldInput(fd, row.values[fd.key], row)}${this.errorFor(row.uid, fd.key)}</td>${afterField(fd, recorderCell(row))}`).join('')}
                ${legacy ? `<td data-judge="${row.uid}">${this.judgeCell(s, row.values)}</td>` : ''}
                ${canAdd ? `<td><button class="btn btn-secondary btn-sm" data-del="${row.uid}" title="${row.deleted ? '삭제 취소' : '행 삭제'}">${row.deleted ? '↺' : '✕'}</button></td>` : ''}
              </tr>`).join('') : `<tr><td colspan="${s.fields.length + 3}" class="te-empty">${s.system_rows ? '아직 입고된 LOT가 없습니다' : '행이 없습니다.'}</td></tr>`}</tbody>
          </table></div></div>`;
      }).join('');

      const basicFields = f.requirement
        ? `<div class="form-group"><label class="form-label">대상</label><div class="te-ro te-ro-block">${esc(targetText(d))}</div></div>
           <div class="form-group"><label class="form-label">작업일</label><div class="te-ro te-ro-block">${esc(d.work_date)} <span class="te-hint">(고정)</span></div></div>`
        : `<div class="form-group"><label class="form-label">대상</label><input class="form-control ${cls('subject')}" data-basic="subject" maxlength="100" value="${esc(f.basic.subject)}">${basicErr('subject')}</div>
           <div class="form-group"><label class="form-label">작업일 *</label><input type="date" class="form-control ${cls('work_date')}" data-basic="work_date" value="${esc(f.basic.work_date)}">${basicErr('work_date')}${future}</div>`;

      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(title, f.mode === 'edit' ? '바뀐 부분만 저장됩니다. 노란색=변경, 초록색=추가, 취소선=삭제 예정 · 저장은 필수값을 검사하지 않습니다(작성완료 때 검사)' : '기본 정보와 영역 값을 입력하세요. 필수값(*)은 작성완료 때 검사합니다.', d && d.document_id)}
          ${f.pending.length ? `<div class="te-notice"><strong>다른 사용자가 먼저 수정해서 최신 내용으로 다시 열었습니다.</strong> 아래 변경을 다시 입력하세요.<ul class="te-pending">${f.pending.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>` : ''}
          ${f.errorList.length ? `<div class="te-error-box" id="teErrorBox"><strong>${esc(f.errorTitle || '입력값을 확인하세요.')}</strong><ul>${f.errorList.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
          <div class="card">
            <div class="card-header"><div class="card-title">문서 정보 ${d ? requirementChip(d) : ''}</div><div class="te-hint">작성자: ${author}</div></div>
            ${api.staffId && !canWrite ? `<div class="te-perm-note" id="teFormWriteWhy">${esc(T.WRITE_WHY)} ${T.roleLink()}</div>` : ''}
            <div class="te-grid">
              ${basicFields}
              <div class="form-group"><label class="form-label">담당자</label><div class="te-ro te-ro-block" id="teFormOwners">${owners.length ? T.peopleHtml(owners) : '<span class="te-judge-ng">(없음) ⚠</span>'} <span class="te-hint">(양식 담당자 — ${T.roleLink()})</span></div></div>
              <div class="form-group"><label class="form-label">마감</label><input type="datetime-local" class="form-control ${cls('due_at')}" data-basic="due_at" value="${esc(f.basic.due_at)}">${basicErr('due_at')}</div>
            </div>
            ${d ? `<div class="te-meta">${periodText(f.schema, d)}</div>` : ''}
            ${this.guideHtml(f.schema)}
            ${sectionsHtml}
            ${f.mode === 'edit' ? '<div class="te-hint" style="margin-top:1rem">이탈·개선조치는 문서 상세 화면에서 따로 저장합니다(문서 상태와 상관없이 언제든).</div>' : ''}
            <div class="te-actions">
              <button class="btn btn-secondary" id="btnCancel">취소</button>
              <button class="btn btn-primary" id="btnSave" ${!api.staffId || !canWrite || !this.isDirty() ? 'disabled' : ''}>저장</button>
            </div>
          </div>
        </div>`;
      this.bindForm();
    },

    bindForm() {
      const f = this.form;
      const root = this.root;
      this.rerenderTopBar(() => this.renderForm());
      root.querySelectorAll('[data-basic]').forEach((el) => el.addEventListener('input', () => {
        f.basic[el.dataset.basic] = el.value;
        if (f.mode === 'edit') el.classList.toggle('te-field-changed', f.basic[el.dataset.basic] !== f.originalBasic[el.dataset.basic]);
        this.refreshSave();
      }));
      root.querySelectorAll('[data-row][data-field]').forEach((el) => {
        const handler = () => {
          const row = f.rows.find((r) => r.uid === Number(el.dataset.row));
          const section = f.sectionByKey[row.key];
          const field = section.fields.find((fd) => fd.key === el.dataset.field);
          const value = this.readInput(el, field);
          if (value === undefined) delete row.values[field.key]; else row.values[field.key] = value;
          f.hinted.delete(`${row.uid}.${field.key}`);
          const tr = root.querySelector(`tr[data-tr="${row.uid}"]`);
          if (tr) tr.className = `te-row-${this.rowState(row) || 'same'}${isNonconforming(section, row.values) ? ' te-row-ng' : ''}`;
          root.querySelector(`[data-ng-section="${row.uid}"]`)?.classList.toggle('te-section-ng', isNonconforming(section, row.values));
          const vh = root.querySelector(`[data-verdict-hint="${row.uid}"]`);
          if (vh) vh.hidden = !verdictWarn(section, row.values);
          const judge = root.querySelector(`[data-judge="${row.uid}"]`);
          if (judge) judge.innerHTML = this.judgeCell(section, row.values);
          const computed = withComputed(section, row.values);
          section.fields.filter((fd) => fd.computed).forEach((fd) => {
            const cell = root.querySelector(`[data-computed="${row.uid}.${fd.key}"]`);
            if (cell) cell.innerHTML = this.display(fd, computed[fd.key]);
          });
          this.refreshSave();
        };
        el.addEventListener('input', handler);
        el.addEventListener('change', handler);
      });
      // P8 점검표: O/X/해당 없음 버튼(다시 누르면 빈칸), [매일 항목 모두 O](빈칸만)
      root.querySelectorAll('[data-ox] button').forEach((b) => b.addEventListener('click', () => {
        const [uid, key] = b.parentElement.dataset.ox.split('.');
        const row = f.rows.find((x) => x.uid === Number(uid));
        if (row.values[key] === b.dataset.v) delete row.values[key]; else row.values[key] = b.dataset.v;
        this.renderForm();
      }));
      root.querySelectorAll('[data-all-o]').forEach((b) => b.addEventListener('click', () => {
        const row = f.rows.find((x) => x.uid === Number(b.dataset.allO));
        f.sectionByKey[row.key].fields.filter(isDaily).forEach((fd) => { if (!row.values[fd.key]) row.values[fd.key] = 'O'; });
        this.renderForm();
      }));
      root.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', () => this.addRow(b.dataset.add)));
      root.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => {
        const row = f.rows.find((r) => r.uid === Number(b.dataset.del));
        if (row.sectionId) row.deleted = !row.deleted; else f.rows.splice(f.rows.indexOf(row), 1);
        this.renderForm();
      }));
      root.querySelector('#btnCancel').addEventListener('click', async () => {
        if (f.mode === 'edit' && this.isDirty() && !(await T.confirm('변경 취소', '변경 내용을 버릴까요?', '버리기', 'btn-danger'))) return;
        if (f.mode === 'edit') this.showDetail(f.document.document_id); else this.showList();
      });
      root.querySelector('#btnSave').addEventListener('click', () => this.save());
      const firstError = root.querySelector('.te-error-text');
      if (firstError && f.focusError) {
        f.focusError = false;
        firstError.scrollIntoView({ block: 'center' });
        const input = firstError.parentElement.querySelector('input, select');
        if (input) input.focus({ preventScroll: true });
      }
    },

    refreshSave() {
      const btn = this.root.querySelector('#btnSave');
      if (btn) btn.disabled = !api.staffId || !this.form.canWrite || !this.isDirty();
    },

    basicPayload(source) {
      const out = {};
      Object.entries(source).forEach(([k, v]) => {
        if (k === 'subject' || k === 'due_at') out[k] = v === '' ? null : v;
        else out[k] = v;
      });
      return out;
    },

    async save() {
      const f = this.form;
      const pathMap = {};
      let result;
      if (f.mode === 'create') {
        const sections = [];
        f.schema.sections.forEach((s) => f.rows.filter((r) => r.key === s.key && !r.deleted).forEach((r) => {
          pathMap[`sections[${sections.length}]`] = r.uid;
          sections.push({ section_def: r.key, values: this.userValues(r) });
        }));
        result = await api.post('documents', { template_id: f.template.template_id, ...this.basicPayload(f.basic), sections });
      } else {
        const body = { expected_version: f.document.version };
        const docChanges = this.basicPayload(this.basicChanges());
        if (Object.keys(docChanges).length) body.document = docChanges;
        const add = []; const update = []; const del = [];
        f.rows.forEach((r) => {
          const state = this.rowState(r);
          if (state === 'deleted') { pathMap[`sections.delete[${r.sectionId}]`] = r.uid; del.push(r.sectionId); }
          else if (state === 'new') { pathMap[`sections.add[${add.length}]`] = r.uid; add.push({ section_def: r.key, values: this.userValues(r) }); }
          else if (state === 'changed') { pathMap[`sections.update[${update.length}]`] = r.uid; update.push({ section_id: r.sectionId, values: this.rowPatch(r) }); }
        });
        const sections = {};
        if (add.length) sections.add = add;
        if (update.length) sections.update = update;
        if (del.length) sections.delete = del;
        if (Object.keys(sections).length) body.sections = sections;
        result = await api.patch(`documents/${f.document.document_id}`, body);
      }
      if (result.ok) {
        T.toast('저장했습니다.', 'success');
        this.showDetail(result.data.document_id);
        return;
      }
      const data = result.data || {};
      if (data.code === 'VERSION_CONFLICT') {
        await this.handleConflict(data);
        return;
      }
      if (data.code === 'DOCUMENT_LOCKED' || data.code === 'DOCUMENT_NOT_FOUND') {
        await T.modal({ title: '저장할 수 없습니다', body: `<p>${esc(data.message)}</p>`, buttons: [{ label: data.code === 'DOCUMENT_LOCKED' ? '상세로' : '목록으로', value: true, cls: 'btn-primary' }] });
        if (data.code === 'DOCUMENT_LOCKED') this.showDetail(f.document.document_id); else this.showList();
        return;
      }
      this.applyErrors(data, pathMap);
    },

    // ================================================= DOC-SC-06 수정 충돌 (ISS-001)
    changeSummary() {
      const f = this.form;
      const labels = { subject: '대상', work_date: '작업일', due_at: '마감' };
      const out = Object.entries(this.basicChanges()).map(([k, v]) => `${labels[k]}: ${v === '' ? '(비움)' : v}`);
      f.schema.sections.forEach((s) => {
        const fieldLabel = (key) => (s.fields.find((fd) => fd.key === key) || { label: key }).label;
        const fmt = (values) => Object.entries(values).map(([k, v]) => `${fieldLabel(k)} ${v === null ? '(비움)' : v}`).join(', ');
        f.rows.filter((r) => r.key === s.key).forEach((r, i) => {
          const state = this.rowState(r);
          const where = s.repeat ? `${s.label} ${i + 1}행` : s.label;
          if (state === 'changed') out.push(`${where}: ${fmt(this.rowPatch(r))}`);
          else if (state === 'deleted') out.push(`${where} 삭제`);
          else if (state === 'new') out.push(`${s.label} 행 추가: ${fmt(this.userValues(r))}`);
        });
      });
      return out;
    },

    async handleConflict(data) {
      const f = this.form;
      const info = (data.details || [])[0] || {};
      const pending = this.changeSummary();
      const reopen = await T.modal({
        title: '다른 사용자가 먼저 수정했습니다',
        body: `<p>이 문서는 내가 연 뒤에 다시 저장되었습니다.<br>
          <span class="te-hint">내가 연 버전 ${esc(info.expected ?? f.document.version)} → 현재 버전 ${esc(info.current ?? '?')}${info.updated_at ? `, 마지막 수정 ${esc(T.fmtDateTime(info.updated_at))}` : ''}</span></p>
          ${pending.length ? `<p style="margin-top:.6rem"><b>내가 바꾼 내용</b> (다시 입력해야 함)</p><ul class="te-pending">${pending.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}`,
        buttons: [{ label: '이 화면에 머물기', value: false }, { label: '최신 내용으로 다시 열기', value: true, cls: 'btn-primary' }],
      });
      if (!reopen) return;
      const latest = await api.get(`documents/${f.document.document_id}`);
      if (!latest.ok) { T.toast(T.errorText(latest), 'error'); this.showList(); return; }
      this.openForm({ document: latest.data, pending });
    },

    applyErrors(data, pathMap, completion = false) {
      const f = this.form;
      f.errors = {};
      f.errorList = [];
      f.errorTitle = completion ? '작성완료할 수 없습니다. 아래 항목을 채운 뒤 저장하고 다시 작성완료하세요.' : null;
      (data.details || []).forEach((e) => {
        const path = e.path || '';
        const basic = /^(?:document\.)?(subject|work_date|due_at)$/.exec(path);
        const row = /^(sections(?:\.(?:update|add|delete))?\[[^\]#]+\])(?:\.values\.(\w+)|\.round)?$/.exec(path);
        const numbered = /^sections\[(\w+)#(\d+)\]\.values\.(\w+)$/.exec(path); // 작성완료 검사(VR-19)
        const section = /^sections\[(\w+)\]$/.exec(path);
        if (basic) f.errors[`basic.${basic[1]}`] = e.message;
        else if (numbered) {
          const target = f.rows.find((r) => r.key === numbered[1] && r.rowNo === Number(numbered[2]));
          if (target) f.errors[`${target.uid}.${numbered[3]}`] = e.message;
        } else if (row && pathMap[row[1]] !== undefined) f.errors[`${pathMap[row[1]]}.${row[2] || 'round'}`] = e.message;
        else if (section && f.sectionByKey[section[1]]) f.errors[`section.${section[1]}`] = e.message;
        f.errorList.push(e.path === 'deviations' ? `${e.message} — 이탈·개선조치는 저장 후 문서 상세 화면에서 입력합니다.` : this.problemText(e));
      });
      if (!f.errorList.length) f.errorList.push(data.message || '저장에 실패했습니다.');
      if (!completion) T.toast(`[${data.code}] ${data.message}`, 'error');
      f.focusError = true;
      this.renderForm();
    },

    // 작성완료 검사 결과 한 줄 (DOC-SC-09). 행 오류는 "영역 · 행 이름: 메시지"
    problemText(e, schema, sections) {
      const sch = schema || (this.form && this.form.schema);
      const rows = sections || (this.form && this.form.document && this.form.document.sections) || [];
      const m = /^sections\[(\w+)#(\d+)\]\.values\.(\w+)$/.exec(e.path || '');
      if (!m || !sch) return e.message;
      const s = sch.sections.find((x) => x.key === m[1]);
      if (!s) return e.message;
      if (!s.repeat) return `${s.label}: ${e.message}`;
      const row = rows.find((x) => x.section_def === m[1] && x.row_no === Number(m[2]));
      const name = row && row.values && row.values.lot_number ? row.values.lot_number : `${m[2]}행`;
      return `${s.label} ${name}: ${e.message}`;
    },

    // ================================================= DOC-SC-04 상세
    async showDetail(id) {
      const r = await api.get(`documents/${id}`);
      if (!r.ok) {
        this.root.innerHTML = `<div class="fade-in">${T.topBar('문서 상세', '')}<div class="card te-empty">${r.status === 404 ? '문서를 찾을 수 없습니다 (삭제되었을 수 있습니다).' : esc(T.errorText(r))}<br><br><button class="btn btn-secondary" id="btnBack">목록</button></div></div>`;
        this.rerenderTopBar(() => this.showDetail(id));
        this.root.querySelector('#btnBack').addEventListener('click', () => this.goBack());
        return;
      }
      const d = r.data;
      const t = await api.get(`templates/${d.template.template_id}`);
      const schema = t.ok ? t.data.schema : { sections: [] };
      if (this.devDocument !== d.document_id) { this.devDrafts = []; this.devDocument = d.document_id; }
      const canEdit = EDITABLE.includes(d.status);
      const canComplete = COMPLETABLE.includes(d.status);
      const canReopen = d.status === 'completed';
      const fixing = d.correction || null; // 정정 진행 중(정정 중·작성완료·결재중)
      const canCorrect = d.status === 'approved' && !fixing;
      // 작성 요구 문서는 삭제 불가(C-3) — 주기 문서는 예외(C4 S6, D-149 — ISS-028)
      const canDelete = d.status === 'draft' && !d.submitted_at && (!d.record_key || d.requirement === 'periodic') && !fixing; // 정정 중 숨김
      // P8: 작성 안 함 = 작성중 + 주기 작성 요구 문서(skippable 양식 + record_key), 되돌리기 = 작성 안 함일 때(p8-s1 6장)
      const canSkip = d.status === 'draft' && d.skippable && !!d.record_key;
      const skipped = d.status === 'skipped';
      // 유효 승인본(가장 큰 attempt의 승인 회차, APR A5 effective) — 정정 배너용
      let effective = null;
      if (fixing) {
        const h = await api.get(`documents/${d.document_id}/approval-requests`);
        effective = h.ok ? h.data.items.find((x) => x.effective) || null : null;
      }
      const notes = {
        completed: '작성완료된 문서입니다. 수정하려면 [작성 재개]를 누르세요. 상신은 아래 결재 영역에서 합니다.',
        submitted: '결재 진행 중인 문서는 수정할 수 없습니다.',
        approved: '승인된 문서는 수정할 수 없습니다.',
        rejected: '반려된 문서입니다. 수정한 뒤 작성완료하면 재상신할 수 있습니다(삭제는 불가 — 상신 이력 보존).',
        correcting: '정정 중입니다. 수정한 뒤 작성완료하고 다시 상신하세요.',
      };
      if (fixing && d.status === 'completed') notes.completed = '정정 내용을 작성완료했습니다. 아래 결재 영역에서 상신하세요. 고치려면 [작성 재개](정정 중으로 돌아감).';
      if (d.status === 'approved') notes.approved = '승인된 문서는 수정할 수 없습니다. 고쳐야 하면 [정정 시작]을 누르세요.';
      if (d.status === 'draft' && d.submitted_at) notes.draft = '상신 이력이 있어 삭제할 수 없습니다.';
      if (d.status === 'draft' && d.record_key) notes.draft = '작성 요구로 만들어진 문서입니다. 삭제할 수 없습니다.';
      if (canSkip) notes.draft = '주기 작성 요구 문서입니다. 휴무 등 작성하지 않는 날은 [작성 안 함]을 누르세요. 날짜를 잘못 골라 만들었으면 [삭제] — 규칙상 만드는 평일은 다음 주기 생성 때 다시 만들어집니다.';
      if (skipped) notes.skipped = `작성 안 함: <b>${esc(d.skip.reason)}</b> — ${T.personHtml(d.skip.by)}, ${T.fmtDateTime(d.skip.at)}. 다시 작성하려면 [되돌리기](입력했던 값은 그대로).`;
      const counts = checkCounts(schema, d);
      const info = d.sections.find((s) => s.section_def === 'info');
      const inspector = info && info.values.inspector ? `<span>점검자 <b>${T.personHtml(info.values.inspector)}</b></span>` : '';
      // P14 S1-Q1: [정정 시작]은 담당자·팀장만(서버 permissions.start_correction) — 아니면 비활성 + 이유
      const mayCorrect = !!(d.permissions && d.permissions.start_correction);
      // P14 r13(D-201) ROLE-R07: 작성 버튼은 상태로 보이되 permissions.write가 없으면 비활성 + 머리 아래 한 줄(화면 r6 3.3)
      const mayWrite = !!(d.permissions && d.permissions.write);
      this.mayWrite = !!api.staffId && mayWrite;  // 섹션·파일·개선조치 영역이 함께 씀
      const writeOff = !api.staffId ? 'disabled title="현재 사용자를 선택하세요"' : (mayWrite ? '' : `disabled title="${esc(T.WRITE_WHY)}"`);
      const anyWrite = canEdit || canComplete || canReopen || canDelete || canSkip || skipped || d.status === 'correcting' || !!schema.files || (d.deviations || []).length || EDITABLE.includes(d.status);
      const correctOff = !api.staffId ? 'disabled title="현재 사용자를 선택하세요"' : (mayCorrect ? '' : 'disabled title="이 양식의 담당자나 HACCP팀장만 정정할 수 있습니다"');
      const sections = this.sectionsHtml(schema, d, { detail: true });
      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(`문서 #${d.document_id} · ${d.template.name} v${d.template.version}`, '문서 상세', d.document_id)}
          <div class="card">
            <div class="card-header">
              <div class="card-title">${statusCell(d.status, !!fixing)} ${requirementChip(d)}</div>
              <div class="page-actions">
                <button class="btn btn-secondary btn-sm" id="btnList">${this.detailBack ? '뒤로' : '목록'}</button>
                ${PRINT_TYPES.includes(d.template.type_code) ? `<button class="btn btn-secondary btn-sm" id="btnPrint" ${PRINTABLE.includes(d.status) ? (d.template.type_code === 'D03' ? `title="입고일 ${d.work_date} 육안검사일지(그날 D03 전체)"` : WEEK_PRINT_TYPES.includes(d.template.type_code) ? 'title="이 문서가 들어간 주의 점검표"' : d.template.type_code === 'D11' ? 'title="이 문서가 들어간 달의 방충방서점검표"' : '') : 'disabled title="작성완료 뒤 출력할 수 있습니다"'}>출력</button>` : ''}
                ${canEdit ? `<button class="btn btn-primary btn-sm" id="btnEdit" ${writeOff}>수정</button>` : ''}
                ${canComplete ? `<button class="btn btn-primary te-btn-complete btn-sm" id="btnComplete" ${writeOff}>작성완료</button>` : ''}
                ${canReopen ? `<button class="btn btn-secondary btn-sm" id="btnReopen" ${writeOff}>작성 재개</button>` : ''}
                ${canCorrect ? `<button class="btn btn-warning btn-sm" id="btnCorrect" ${correctOff}>정정 시작</button>` : ''}
                ${canDelete ? `<button class="btn btn-danger btn-sm" id="btnDelete" ${writeOff}>삭제</button>` : ''}
                ${canSkip ? `<button class="btn btn-secondary btn-sm" id="btnSkip" ${writeOff}>작성 안 함</button>` : ''}
                ${skipped ? `<button class="btn btn-primary btn-sm" id="btnUnskip" ${writeOff}>되돌리기</button>` : ''}
              </div>
            </div>
            ${fixing ? this.correctionBanner(d, fixing, effective) : ''}
            ${notes[d.status] ? `<div class="${skipped ? 'te-skip-note' : 'te-status-note'}" id="teStatusNote">${notes[d.status]}</div>` : ''}
            ${api.staffId && !mayWrite && anyWrite ? `<div class="te-perm-note" id="teWriteWhy">${esc(T.WRITE_WHY)} ${T.roleLink()}</div>` : ''}
            ${canCorrect && api.staffId && !mayCorrect ? `<div class="te-perm-note" id="teCorrectWhy">이 양식의 담당자나 HACCP팀장만 정정할 수 있습니다. ${T.roleLink()}</div>` : ''}
            <div class="te-meta">
              <span>대상 <b id="teTarget">${targetHtml(d)}</b></span><span>작업일 <b>${d.work_date}</b></span>
              <span id="teAuthor">작성자 <b>${T.authorHtml(d)}</b></span><span id="teOwners">담당자 <b>${T.peopleHtml(d.owner_ids || [], { empty: '(없음) ⚠' })}</b> <span class="te-hint">(양식)</span></span>${inspector}
              <span>마감 <b>${T.fmtDateTime(d.due_at)}</b></span>${periodText(schema, d)}
            </div>
            <div class="te-meta" style="margin-top:.25rem">
              <span>작성 ${T.fmtDateTime(d.created_at)}</span><span>최종 수정 ${T.fmtDateTime(d.updated_at)}</span>
              ${d.completed_at && d.status !== 'rejected' ? `<span id="teCompleted">작성완료 ${T.fmtDateTime(d.completed_at)} (${T.personHtml(d.completed_by)})</span>` : ''}
              ${d.submitted_at ? `<span>상신 ${T.fmtDateTime(d.submitted_at)}</span>` : ''}<span class="te-hint">v${d.version}</span>
            </div>
            ${WEEK_TYPES.includes(d.template.type_code) ? '<div class="te-meta" id="teWeekStrip"></div>' : ''}
            ${counts ? `<div class="te-check-sum" id="teCheckSum"><span>점검표: ${countsText(counts)}</span>${counts.blank && COMPLETABLE.includes(d.status) ? '<span class="te-hint">빈칸이 있으면 작성완료할 수 없습니다</span>' : ''}</div>` : ''}
            ${this.guideHtml(schema)}
            ${sections}
            ${schema.files ? '<div id="teFiles"></div>' : ''}
            <div id="teDeviationArea"></div>
            <div id="teApprovalArea"></div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showDetail(id));
      const $ = (sel) => this.root.querySelector(sel);
      $('#btnList').addEventListener('click', () => this.goBack());
      // P12: 새 탭 인쇄용 페이지(PRT-SC-01). 사용자 선택과 무관(읽기 전용)
      $('#btnPrint')?.addEventListener('click', () => window.open(`/print/?document_id=${d.document_id}`, '_blank'));
      $('#btnEdit')?.addEventListener('click', () => this.openForm({ document: d }));
      $('#btnDelete')?.addEventListener('click', () => this.confirmDelete(d));
      $('#btnComplete')?.addEventListener('click', () => this.confirmComplete(d, schema));
      $('#btnReopen')?.addEventListener('click', () => this.reopen(d));
      $('#btnSkip')?.addEventListener('click', () => this.openSkip(
        [{ document_id: d.document_id, version: d.version, status: d.status, lot: `${d.work_date} (${dow(d.work_date)})` }],
        { title: `${d.work_date} (${dow(d.work_date)}) ${d.template.name}`, single: true, onDone: () => this.showDetail(d.document_id) },
      ));
      $('#btnUnskip')?.addEventListener('click', () => this.unskip(d));
      $('#btnCorrect')?.addEventListener('click', () => this.openCorrection(d, effective));
      $('#btnFixCancel')?.addEventListener('click', () => this.cancelCorrection(d, effective));
      $('#btnEffective')?.addEventListener('click', () => {
        if (window.TempEntryApproval) window.TempEntryApproval.showRequest(Number($('#btnEffective').dataset.request), { from: 'doc', documentId: d.document_id });
      });
      this.root.querySelectorAll('#teTarget [data-prod-batch]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        T.productionPage().openBatch(Number(a.dataset.prodBatch), 'documents');
      }));
      this.root.querySelectorAll('#teTarget [data-lot]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        T.open('temp-lot-docs', { lotId: Number(a.dataset.lot), back: { page: 'temp-doc', documentId: d.document_id } });
      }));
      this.root.querySelectorAll('[data-dev-for]').forEach((b) => b.addEventListener('click', () => {
        this.devDrafts.push({ section_id: b.dataset.devFor ? Number(b.dataset.devFor) : null, description: b.dataset.devText });
        this.renderDeviations(d, schema);
        this.root.querySelector('#teDeviationArea').scrollIntoView({ block: 'center' });
      }));
      // 작성 안 함: 이탈·개선조치는 있으면 읽기만, 결재 영역 숨김(p8-s1 3장·6장)
      if (skipped) {
        if ((d.deviations || []).length) $('#teDeviationArea').innerHTML = this.deviationsHtml(schema, d);
      } else this.renderDeviations(d, schema);
      this.applyOpenFocus(d, schema, skipped);
      if (schema.files) this.renderFiles(d, schema);
      if (WEEK_TYPES.includes(d.template.type_code)) this.renderWeekStrip(d);
      // P3 결재 영역 (WF-SC-01) — temp-entry/approval/approval.js
      const area = $('#teApprovalArea');
      if (window.TempEntryApproval && !skipped) window.TempEntryApproval.mountArea(area, d, () => this.showDetail(id));
    },

    // 문서 내용(섹션) 읽기 전용 표시. 결재 요청 상세(WF-SC-04)도 스냅샷을 이 함수로 그린다.
    sectionsHtml(schema, d, { detail = false } = {}) {
      return schema.sections.map((s) => {
        const rows = d.sections.filter((x) => x.section_def === s.key);
        if (isChecklist(s)) return this.checklistDetailHtml(s, d, detail);
        if (!s.repeat) {
          const v = rows[0] ? rows[0].values : {};
          const hints = (rows[0] && rows[0].hints) || {}; // P7 S6(ISS-025): 반복 아닌 섹션(D03 v2 검사)도 자동 제안 표시
          const ng = !!rows[0] && isNonconforming(s, v);
          const add = ng && detail && this.mayWrite ? ` <button class="btn btn-secondary btn-sm te-dev-add" data-dev-for="" data-dev-text="${esc(`${s.label} 부적합`)}">개선조치 추가</button>` : '';
          return `<div class="te-section${ng ? ' te-section-ng' : ''}"><div class="te-section-title">${esc(s.label)}${ng ? ' <span class="te-judge-ng">⚠ 부적합</span>' : ''}${add}</div>
            <dl class="te-kv">${s.fields.map((fd) => `<div${verdictFocus(d.template && d.template.type_code, fd) ? ' class="te-verdict-kv"' : ''}><dt>${esc(fd.label)}</dt><dd>${this.display(fd, withComputed(s, v)[fd.key], hints[fd.key])}</dd></div>`).join('')}</dl></div>`;
        }
        const legacy = this.legacyJudge(s);
        const canDev = detail && this.mayWrite && !!s.nonconforming;
        const body = rows.map((x, i) => {
          const values = withComputed(s, x.values);
          const ng = this.judge(s, x.values) === 'ng';
          const rowName = x.values.lot_number || `${i + 1}행`;
          return `<tr class="${ng ? 'te-row-ng' : ''}" data-section-row="${x.section_id}">
            <td>${i + 1}</td>${s.fields.map((fd) => `<td>${this.display(fd, values[fd.key], x.hints && x.hints[fd.key])}</td>`).join('')}
            ${legacy ? `<td>${this.judgeCell(s, x.values)}</td>` : ''}
            <td class="te-hint">${ng && !legacy && !hasComputed(s) ? '<span class="te-judge-ng">⚠ 부적합</span><br>' : ''}${T.fmtDateTime(x.recorded_at)} · ${T.personHtml(x.recorded_by)}${ng && canDev ? `<br><button class="btn btn-secondary btn-sm te-dev-add" data-dev-for="${x.section_id}" data-dev-text="${esc(`${s.label} ${rowName} 부적합`)}">개선조치 추가</button>` : ''}</td></tr>`;
        }).join('')
          || `<tr><td colspan="${s.fields.length + 3}" class="te-empty">${s.system_rows ? '아직 입고된 LOT가 없습니다' : '행이 없습니다.'}</td></tr>`;
        return `<div class="te-section"><div class="te-section-title">${esc(s.label)} <span class="te-hint">${rows.length}행</span></div>
          <div class="te-table-wrap"><table class="data-table"><thead><tr><th>#</th>${s.fields.map((fd) => `<th>${esc(fd.label)}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>`).join('')}${legacy ? '<th>판정</th>' : ''}<th>기록</th></tr></thead>
          <tbody>${body}</tbody></table></div></div>`;
      }).join('');
    },

    // 상신 당시 이탈·개선조치(스냅샷, FR-27). 결재 요청 상세(WF-SC-04)에서 쓴다.
    deviationsHtml(schema, d, title = '이탈·개선조치') {
      const list = d.deviations || [];
      const rowName = (sid) => {
        for (const s of schema.sections.filter((x) => x.repeat)) {
          const rows = d.sections.filter((x) => x.section_def === s.key);
          const i = rows.findIndex((x) => x.section_id === sid);
          if (i >= 0) return `${s.label} ${rows[i].values.lot_number || `${i + 1}행`}`;
        }
        return sid ? `행 #${sid}` : '–';
      };
      const hasRows = schema.sections.some((x) => x.repeat) || list.some((x) => x.section_id);
      return `<div class="te-section" id="teSnapDeviation"><div class="te-section-title">${esc(title)} <span class="te-hint">${list.length}건</span></div>
        ${list.length ? `<div class="te-table-wrap"><table class="data-table"><thead><tr>${hasRows ? '<th>관련 행</th>' : ''}<th>한계기준 이탈내용</th><th>조치자</th><th>개선조치 및 결과</th><th>확인자</th></tr></thead>
        <tbody>${list.map((x) => `<tr>${hasRows ? `<td>${esc(rowName(x.section_id))}</td>` : ''}<td>${esc(x.description)}</td><td>${T.personHtml(x.actor_id)}</td>
          <td>${esc(x.action_result || '-')}</td><td>${T.peopleHtml(x.checker_ids || [], { max: 10, empty: '-' })}</td></tr>`).join('')}</tbody></table></div>`
        : '<p class="te-hint">기록된 개선조치가 없습니다.</p>'}</div>`;
    },

    display(field, value, hint) {
      if (value === undefined || value === null || value === '') {
        if (hint !== undefined) return `<span class="te-hint" title="저장된 값 없음 — 같은 LOT 성적서 기준 자동 제안">${esc(hint)} (자동)</span>`;
        return '<span class="te-hint">-</span>';
      }
      if (field.type === 'bool') return value ? '예' : '아니오';
      if (field.type === 'staff') return T.personHtml(value);
      if (field.type === 'datetime') return esc(String(value).replace('T', ' '));
      if (field.display === 'hm' && typeof value === 'number') return esc(fmtMinutes(value));
      if (field.computed) {
        const bad = value === field.computed.else;
        return `<span class="${bad ? 'te-judge-ng' : 'te-judge-ok'}">${bad ? '⚠ ' : ''}${esc(value)}</span>`;
      }
      return esc(optionLabel(field, value));
    },

    // ================================================= DOC-SC-07 첨부 파일 영역 (스프린트 3, D01·D02)
    // 올리기는 파일마다 한 요청(multipart, A11) — 한 파일이 실패해도 나머지는 올린다(형식·크기 오류는 파일별 표시).
    // 올리기·연결·끊기마다 문서 버전 +1 → 다음 요청은 응답의 document_version을 쓴다. 상세 화면에서만(폼 저장과 별개).
    fileSize(n) {
      if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
      return `${Math.max(1, Math.round(n / 1024))}KB`;
    },

    renderFiles(d, schema) {
      const el = this.root.querySelector('#teFiles');
      if (!el) return;
      const rule = schema.files || {};
      const can = EDITABLE.includes(d.status);
      const on = this.mayWrite;  // r13 ROLE-R07 — 현재 사용자 있음 + permissions.write
      const results = this.fileResults && this.fileResults.documentId === d.document_id ? this.fileResults.lines : [];
      this.fileResults = null;
      const icon = (mime) => (mime === 'application/pdf' ? '📄' : '🖼');
      const shared = (x) => (x.shared_count > 1 ? `<span class="te-file-shared" title="같은 파일을 다른 문서도 씁니다(끊어도 파일은 남음)">다른 문서 ${x.shared_count - 1}곳과 공유</span>` : '<span class="te-hint">이 문서</span>');
      const lockedNote = {
        completed: '작성완료 문서입니다. 파일을 바꾸려면 [작성 재개]를 누르세요.',
        submitted: '결재 중인 문서는 파일을 볼 수만 있습니다.',
        approved: '승인된 문서는 파일을 볼 수만 있습니다. 고쳐야 하면 [정정 시작].',
      };
      el.innerHTML = `
        <div class="te-section te-files" id="teFileArea">
          <div class="te-section-head"><span class="te-section-title">증빙 파일 <span class="te-hint" id="teFileCount">${d.files.length}개 · PDF·JPG·PNG, 파일당 20MB 이하${rule.min ? ` · 작성완료에는 ${rule.min}개 이상` : ''}</span></span>
            ${d.files.length ? `<button class="btn btn-secondary btn-sm" id="teFilePrintAll" data-file-print-all title="첨부 원본을 모두 인쇄(사진은 한 번에, PDF는 파일마다 인쇄 창)">모두 인쇄</button>` : ''}</div>
          ${rule.kinds ? `<p class="te-hint">서류 종류(${rule.kinds.map(esc).join(' / ')})는 기본정보의 [서류 종류]에서 고릅니다.</p>` : ''}
          ${results.length ? `<ul class="te-result-list" id="teFileResults">${results.map((x) => (x.ok
            ? `<li class="te-result-ok-line">✅ <b>${esc(x.name)}</b> <span>${esc(x.text)}</span></li>`
            : `<li class="te-result-fail-line">⚠ <b>${esc(x.name)}</b> <span>${esc(x.text)}</span></li>`)).join('')}</ul>` : ''}
          <div class="te-table-wrap"><table class="data-table" id="teFileTable">
            <thead><tr><th>파일</th><th>크기</th><th>올린 사람·시각</th><th>연결</th><th></th></tr></thead>
            <tbody>${d.files.map((x) => `<tr data-file="${x.file_id}">
              <td>${icon(x.mime_type)} ${esc(x.original_name)}</td>
              <td class="te-nowrap">${this.fileSize(x.size_bytes)}</td>
              <td class="te-nowrap">${T.personHtml(x.uploaded_by)} · ${T.fmtDateTime(x.uploaded_at)}</td>
              <td>${shared(x)}</td>
              <td class="te-nowrap"><a class="btn btn-secondary btn-sm" href="/api/v1/files/${x.file_id}" target="_blank" rel="noopener" data-file-view="${x.file_id}">보기</a>
                <button class="btn btn-secondary btn-sm" data-file-print="${x.file_id}" title="이 파일 원본 인쇄">인쇄</button>
                ${can ? `<button class="btn btn-secondary btn-sm" data-file-detach="${x.file_id}" title="이 문서에서 연결 끊기" ${on ? '' : 'disabled'}>✕</button>` : ''}</td>
            </tr>`).join('') || `<tr><td colspan="5" class="te-empty">${can ? '아직 올린 파일이 없습니다. 아래에서 파일을 고르거나 끌어 놓으세요.' : '파일이 없습니다.'}</td></tr>`}</tbody>
          </table></div>
          ${can ? `<div class="te-file-actions">
              <label class="te-dropzone ${on ? '' : 'te-disabled'}" id="teDrop">
                <input type="file" id="teFileInput" multiple accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png" hidden ${on ? '' : 'disabled'}>
                📎 파일 선택 / 끌어 놓기 <span class="te-hint">(여러 개 가능)</span>
              </label>
              <button class="btn btn-secondary btn-sm" id="teFilePick" ${on ? '' : 'disabled'}>이전 파일 불러오기</button>
              ${api.staffId ? (on ? '' : '<span class="te-hint">작성 권한이 없습니다(위 안내).</span>') : '<span class="te-hint">현재 사용자를 선택하세요.</span>'}
            </div>` : (lockedNote[d.status] ? `<p class="te-hint">${lockedNote[d.status]}</p>` : '')}
          ${this.filePreviewsHtml(d.files)}
        </div>`;
      // P12 DP-19: 미리보기·인쇄는 상태·쓰기 권한과 무관(원본 서류)
      this.bindFilePrint(el, d.files);
      if (!can || !on) return;
      const input = el.querySelector('#teFileInput');
      const drop = el.querySelector('#teDrop');
      input.addEventListener('change', () => { if (input.files.length) this.uploadFiles(d, [...input.files]); });
      ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('te-drop-over'); }));
      ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove('te-drop-over'); }));
      drop.addEventListener('drop', (e) => { const list = [...(e.dataTransfer?.files || [])]; if (list.length) this.uploadFiles(d, list); });
      el.querySelector('#teFilePick').addEventListener('click', () => this.openFilePicker(d, schema));
      el.querySelectorAll('[data-file-detach]').forEach((b) => b.addEventListener('click', () => {
        const file = d.files.find((x) => x.file_id === Number(b.dataset.fileDetach));
        this.detachFile(d, file);
      }));
    },

    // P12 DP-19 첨부 원본 미리보기 카드 — 문서 상세와 결재 요청 상세(상신 당시 파일)가 같이 씀
    filePreviewsHtml(files, id = 'teFilePreviews') {
      if (!files.length) return '';
      const icon = (mime) => (mime === 'application/pdf' ? '📄' : '🖼');
      return `<div class="te-file-previews" id="${id}">${files.map((x) => `
            <figure class="te-file-preview" data-file-preview="${x.file_id}">
              ${isPdf(x)
                ? `<iframe src="/api/v1/files/${x.file_id}#toolbar=0&navpanes=0&view=FitH" title="${esc(x.original_name)}" loading="lazy"></iframe>`
                : `<a href="/api/v1/files/${x.file_id}" target="_blank" rel="noopener"><img src="/api/v1/files/${x.file_id}" alt="${esc(x.original_name)}" loading="lazy"></a>`}
              <figcaption><span title="${esc(x.original_name)}">${icon(x.mime_type)} ${esc(x.original_name)}</span>
                <button class="btn btn-secondary btn-sm" data-file-print="${x.file_id}">인쇄</button></figcaption>
            </figure>`).join('')}</div>`;
    },

    // [인쇄]·[모두 인쇄] 연결. files는 살아 있는 목록 — 결재 화면이 지워진 파일을 빼면 [모두 인쇄]에서도 빠짐.
    // 미리보기·인쇄는 상태·쓰기 권한과 무관(원본 서류)
    bindFilePrint(el, files) {
      el.querySelectorAll('[data-file-print]').forEach((b) => b.addEventListener('click', () => {
        const file = files.find((x) => x.file_id === Number(b.dataset.filePrint));
        if (!file) return;
        if (isPdf(file)) printPdf(file.file_id); else printImages([file.file_id]);
      }));
      el.querySelector('[data-file-print-all]')?.addEventListener('click', () => this.printAllFiles(files));
    },

    // P12 DP-19 [모두 인쇄]: 사진은 인쇄용 페이지 한 번, PDF는 파일마다 인쇄 창 — 다음 PDF는 확인 뒤
    async printAllFiles(files) {
      const images = files.filter((x) => !isPdf(x)).map((x) => x.file_id);
      const pdfs = files.filter(isPdf);
      printImages(images);
      for (let i = 0; i < pdfs.length; i += 1) {
        if (i > 0 || images.length) {
          const go = await T.modal({
            title: '다음 파일 인쇄',
            body: `<p>앞 인쇄 창을 닫은 뒤 [인쇄]를 누르세요.</p><p><b>${esc(pdfs[i].original_name)}</b> <span class="te-hint">(PDF ${i + 1}/${pdfs.length})</span></p>`,
            buttons: [{ label: '그만', value: false }, { label: '인쇄', value: true, cls: 'btn-primary' }],
          });
          if (!go) return;
        }
        printPdf(pdfs[i].file_id);
      }
    },

    // 파일마다 한 요청. 버전 충돌이면 최신 버전을 읽어 한 번 더(다른 사람이 그사이 저장한 경우)
    async fileRequests(d, jobs) {
      let version = d.version;
      const lines = [];
      for (const job of jobs) {
        let res = await job.send(version);
        if (!res.ok && res.data && res.data.code === 'VERSION_CONFLICT') {
          const latest = await api.get(`documents/${d.document_id}`);
          if (latest.ok) { version = latest.data.version; res = await job.send(version); }
        }
        if (res.ok) { version = res.data.document_version; lines.push({ ok: true, name: job.name, text: job.okText }); continue; }
        const detail = res.data && res.data.details && res.data.details[0];
        lines.push({ ok: false, name: job.name, text: `[${res.data?.code || res.status}] ${detail?.message || T.errorText(res)}` });
        if (res.data && ['DOCUMENT_LOCKED', 'DOCUMENT_NOT_FOUND'].includes(res.data.code)) break;  // 뒤 파일도 같은 이유로 실패
      }
      return lines;
    },

    async uploadFiles(d, files) {
      const area = this.root.querySelector('#teFileArea');
      if (area) area.classList.add('te-busy');
      T.toast(`파일 ${files.length}개를 올리는 중…`, 'info');
      const lines = await this.fileRequests(d, files.map((f) => ({
        name: f.name, okText: `올림 (${this.fileSize(f.size)})`,
        send: (version) => { const fd = new FormData(); fd.append('file', f); fd.append('expected_version', String(version)); return api.upload(`documents/${d.document_id}/files`, fd); },
      })));
      const ok = lines.filter((x) => x.ok).length;
      T.toast(`파일 ${files.length}개 중 ${ok}개를 올렸습니다.`, ok === files.length ? 'success' : 'error');
      this.fileResults = { documentId: d.document_id, lines };
      this.showDetail(d.document_id);
    },

    async detachFile(d, file) {
      const msg = file.shared_count > 1
        ? `<b>${esc(file.original_name)}</b>의 연결을 끊습니다.<br><span class="te-hint">다른 문서도 쓰는 파일이라 파일은 남습니다.</span>`
        : `<b>${esc(file.original_name)}</b>의 연결을 끊습니다.<br><span class="te-hint">어디에도 쓰이지 않게 되면 파일도 지웁니다(상신된 적 있는 파일은 보존).</span>`;
      if (!(await T.confirm('파일 연결 끊기', msg, '연결 끊기', 'btn-danger'))) return;
      const lines = await this.fileRequests(d, [{ name: file.original_name, okText: '연결 끊음', send: (version) => api.del(`documents/${d.document_id}/files/${file.file_id}?expected_version=${version}`) }]);
      if (lines[0].ok) T.toast('연결을 끊었습니다.', 'success'); else T.toast(lines[0].text, 'error');
      this.fileResults = lines[0].ok ? null : { documentId: d.document_id, lines };
      this.showDetail(d.document_id);
    },

    // ================================================= DOC-SC-08 이전 성적서 불러오기 (F18 검색 → F15 연결)
    openFilePicker(d, schema) {
      const B = window.TempEntryApproval && window.TempEntryApproval.batch;
      if (!B) return;
      const info = (d.sections.find((x) => x.section_def === 'info') || {}).values || {};
      const linked = new Set(d.files.map((x) => x.file_id));
      const st = { item: info.item_name || '', supplier: info.supplier_name || '', days: '90', page: 1, data: null, picked: new Set(), error: '', busy: false };
      const m = B.modal(`이전 파일 불러오기 — ${d.template.name}`);
      const search = async () => {
        const q = new URLSearchParams({ type_code: d.template.type_code, days: st.days, page: String(st.page) });
        if (st.item.trim()) q.set('item', st.item.trim());
        if (st.supplier.trim()) q.set('supplier', st.supplier.trim());
        const r = await api.get(`files?${q}`);
        st.data = r.ok ? r.data : null;
        st.error = r.ok ? '' : `<div class="te-error-box" id="fpError">${esc(T.errorText(r))}</div>`;
        render();
      };
      const render = () => {
        const items = st.data ? st.data.items : [];
        const pages = st.data ? Math.max(1, Math.ceil(st.data.total / st.data.page_size)) : 1;
        m.body.innerHTML = `
          <p class="te-hint">같은 양식(${esc(d.template.type_code)})의 파일만 찾습니다. 연결하면 파일을 복사하지 않고 이 문서에도 붙입니다.</p>
          <div class="te-filters" id="fpFilters">
            <div class="form-group"><label class="form-label">품명</label><input class="form-control" id="fpItem" maxlength="50" value="${esc(st.item)}"></div>
            <div class="form-group"><label class="form-label">매입처</label><input class="form-control" id="fpSupplier" maxlength="50" value="${esc(st.supplier)}"></div>
            <div class="form-group"><label class="form-label">기간</label><select class="form-control" id="fpDays">${[['30', '최근 30일'], ['90', '최근 90일'], ['180', '최근 180일'], ['365', '최근 1년']].map(([v, l]) => `<option value="${v}" ${st.days === v ? 'selected' : ''}>${l}</option>`).join('')}</select></div>
            <button class="btn btn-secondary" id="fpSearch">검색</button>
          </div>
          ${st.error}
          <div class="te-table-wrap"><table class="data-table" id="fpTable">
            <thead><tr><th class="te-check-col"></th><th>파일</th><th>대상(LOT)</th><th>문서</th><th>올린 날</th></tr></thead>
            <tbody>${st.data === null ? '<tr><td colspan="5" class="te-hint">검색 중…</td></tr>' : items.map((x) => {
              const docs = x.documents || [];
              const mine = linked.has(x.file_id);
              return `<tr data-fp="${x.file_id}" class="${st.picked.has(x.file_id) ? 'te-row-picked' : ''}">
                <td class="te-check-col"><input type="checkbox" data-fp-pick="${x.file_id}" ${mine ? 'disabled' : ''} ${st.picked.has(x.file_id) ? 'checked' : ''}></td>
                <td>${esc(x.original_name)} <span class="te-hint">${this.fileSize(x.size_bytes)}</span>${mine ? ' <span class="te-hint">(이미 연결)</span>' : ''}</td>
                <td>${docs.map((y) => esc(y.target_summary || '-')).join('<br>') || '<span class="te-hint">-</span>'}</td>
                <td>${docs.map((y) => `#${y.document_id}`).join(', ') || '-'}</td>
                <td class="te-nowrap">${esc(String(x.uploaded_at || '').slice(5, 10))}</td></tr>`;
            }).join('') || '<tr><td colspan="5" class="te-empty">조건에 맞는 파일이 없습니다.</td></tr>'}</tbody>
          </table></div>
          ${st.data && st.data.total > st.data.page_size ? `<div class="te-pager"><button class="btn btn-secondary btn-sm" id="fpPrev" ${st.page <= 1 ? 'disabled' : ''}>‹</button><span>${st.page} / ${pages} · 총 ${st.data.total}개</span><button class="btn btn-secondary btn-sm" id="fpNext" ${st.page >= pages ? 'disabled' : ''}>›</button></div>` : ''}`;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="fpCancel">취소</button>
          <button class="btn btn-primary" id="fpLink" ${st.picked.size && !st.busy ? '' : 'disabled'}>${st.busy ? '연결 중…' : `연결 (${st.picked.size})`}</button>`;
        const $ = (sel) => m.body.querySelector(sel);
        $('#fpItem').addEventListener('input', (e) => { st.item = e.target.value; });
        $('#fpSupplier').addEventListener('input', (e) => { st.supplier = e.target.value; });
        $('#fpDays').addEventListener('change', (e) => { st.days = e.target.value; });
        $('#fpSearch').addEventListener('click', () => { st.page = 1; search(); });
        $('#fpPrev')?.addEventListener('click', () => { st.page -= 1; search(); });
        $('#fpNext')?.addEventListener('click', () => { st.page += 1; search(); });
        m.body.querySelectorAll('[data-fp-pick]').forEach((c) => c.addEventListener('change', () => {
          const id = Number(c.dataset.fpPick);
          if (c.checked) st.picked.add(id); else st.picked.delete(id);
          render();
        }));
        m.footer.querySelector('#fpCancel').addEventListener('click', m.close);
        m.footer.querySelector('#fpLink').addEventListener('click', link);
      };
      const link = async () => {
        st.busy = true;
        render();
        const byId = Object.fromEntries((st.data ? st.data.items : []).map((x) => [x.file_id, x]));
        const lines = await this.fileRequests(d, [...st.picked].map((id) => {
          const from = (byId[id].documents || [])[0];
          return {
            name: byId[id].original_name, okText: `연결함${from ? ` (#${from.document_id}에서 불러옴)` : ''}`,
            send: (version) => api.post(`documents/${d.document_id}/files`, { expected_version: version, link_file_id: id }),
          };
        }));
        m.close();
        const ok = lines.filter((x) => x.ok).length;
        T.toast(`${lines.length}개 중 ${ok}개를 연결했습니다.`, ok === lines.length ? 'success' : 'error');
        this.fileResults = { documentId: d.document_id, lines };
        this.showDetail(d.document_id);
      };
      render();
      search();
    },

    // ================================================= 이탈·개선조치 영역 (P4-S1 (5), F19~F21)
    // 문서 상태와 상관없이 언제든 저장한다. 문서 버전과 무관하게 개선조치 자기 version으로 충돌을 감지한다.
    // S5 r2(D-198 B2): 다시 그리기 전에 화면의 새 줄 값을 devDrafts에 담는다 — 안 그러면 [+ 추가]·새 줄 [취소] 때
    // 입력한 글자가 사라지고, 확인자는 기본값(담당자 + 팀장)으로 조용히 다시 체크된다
    syncDevDrafts(el) {
      (el ? [...el.querySelectorAll('tr[data-dev^="n"]')] : []).forEach((tr) => {
        const i = Number(tr.dataset.dev.slice(1));
        if (!this.devDrafts[i]) return;
        const v = (k) => tr.querySelector(`[data-k="${k}"]`);
        const num = (x) => (x === '' ? null : Number(x));
        Object.assign(this.devDrafts[i], {
          section_id: v('section_id') ? num(v('section_id').value) : (this.devDrafts[i].section_id ?? null),
          description: v('description').value,
          actor_id: num(v('actor_id').value),
          action_result: v('action_result').value,
        });
      });
    },

    renderDeviations(d, schema, { synced = false } = {}) {
      const el = this.root.querySelector('#teDeviationArea');
      if (!el) return;
      if (!synced) this.syncDevDrafts(el);
      const rowOptions = [];
      schema.sections.filter((s) => s.repeat).forEach((s) => d.sections.filter((x) => x.section_def === s.key).forEach((x, i) => {
        rowOptions.push({ id: x.section_id, label: `${s.label} ${x.values.lot_number || `${i + 1}행`}` });
      }));
      const staffOpts = (sel) => T.staffOptions(sel);
      // P14 ROLE-FR-12 r12(D-199): 확인자는 고르지 않는다 — 새 개선조치를 저장할 때 서버가 이 양식 담당자 + HACCP팀장으로
      // 자동 지정(DOC-DVC-01b: 담당자 먼저, 각각 id 순, 10명까지). 새 줄에는 그 미리 보기만(서버가 저장 때 다시 계산)
      const defaults = [...(d.owner_ids || [])];
      T.leaderIds().slice().sort((a, b) => a - b).forEach((id) => { if (!defaults.includes(id)) defaults.push(id); });
      const truncated = defaults.length > 10;
      const defaultCheckers = defaults.slice(0, 10);
      const rowSelect = (sel) => ['<option value="">– 없음</option>'].concat(rowOptions.map((o) => `<option value="${o.id}" ${String(sel) === String(o.id) ? 'selected' : ''}>${esc(o.label)}</option>`)).join('');
      // 확인 슬롯 1개에 여러 명(D-054). 1명이 확인하면 끝(확인 기능은 ISS-008). r12: 읽기만 — 저장된 확인자 / 새 줄은 자동 지정 미리 보기
      const checkerCell = (x, key) => (key.startsWith('n')
        ? `<span class="te-hint" data-checkers-preview="${defaultCheckers.join(',')}">${T.peopleHtml(defaultCheckers, { max: 10, empty: '(없음)' })} · 저장 때 자동</span>`
        : `<span data-checkers="${(x.checker_ids || []).join(',')}">${T.peopleHtml(x.checker_ids || [], { max: 10, empty: '<span class="te-hint">–</span>' })}</span>`);
      // r13 ROLE-R07: [+ 추가]·저장·삭제는 permissions.write. r14(D-202 Q6 b): 저장된 줄 [저장](수정)은 내가 그 줄 확인자여도
      const me = Number(api.staffId);
      const mayWrite = this.mayWrite;
      const mayEdit = (x) => mayWrite || (!!api.staffId && (x.checker_ids || []).includes(me));
      // P11 DOC-SC-04 확인 칸: 확인됨 → 확인한 사람·시각 / 미확인 + 확인할 수 있음 → [확인] / 미확인 + 다른 사람 → 대기 / 확인자 없음 → –
      // 문서 상태와 무관하게 확인할 수 있음(노출 조건은 대시보드 목록에만 — S2-Q3 a). 새 행(저장 전)은 확인 없음
      // P14 R05(FR-13): 확인 = 지정 확인자 또는 HACCP팀장(확인자 없는 줄도) — 역할 설정 파일 오류면 팀장 예외 없음(C07)
      const leader = !!api.staffId && T.isLeader(me) && !(T.roles && T.roles.config_error);
      const canCheck = (x) => !!api.staffId && ((x.checker_ids || []).includes(me) || leader);
      const checkCell = (x, key) => {
        if (!x.deviation_id) return '<span class="te-hint">새 행</span>';
        if (x.checked_at) return `<span class="te-judge-ok">확인</span> ${T.personHtml(x.checked_by)} · ${esc(String(x.checked_at).slice(5, 16).replace('T', ' '))}`;
        if (canCheck(x)) return `<button class="btn btn-primary btn-sm" data-dev-check="${key}">확인</button>`;
        if (!(x.checker_ids || []).length) return '–';
        return '대기';
      };
      const line = (x, key) => `
        <tr data-dev="${key}">
          ${hasRows ? `<td><select class="form-control" data-k="section_id">${rowSelect(x.section_id)}</select></td>` : ''}
          <td><input class="form-control" data-k="description" maxlength="500" value="${esc(x.description || '')}" placeholder="이탈내용(필수)"></td>
          <td><select class="form-control" data-k="actor_id">${staffOpts(x.actor_id)}</select></td>
          <td><input class="form-control" data-k="action_result" maxlength="1000" value="${esc(x.action_result || '')}"></td>
          <td>${checkerCell(x, key)}</td>
          <td class="te-nowrap">${checkCell(x, key)}</td>
          <td class="te-nowrap"><button class="btn btn-primary btn-sm" data-dev-save="${key}" ${(x.deviation_id ? mayEdit(x) : mayWrite) ? '' : `disabled title="${esc(T.WRITE_WHY)}"`}>저장</button>
            <button class="btn btn-secondary btn-sm" data-dev-del="${key}" ${x.deviation_id && !mayWrite ? `disabled title="${esc(T.WRITE_WHY)}"` : ''}>${x.deviation_id ? '삭제' : '취소'}</button></td>
        </tr>`;
      const saved = d.deviations || [];
      const nonconforming = schema.sections.some((s) => d.sections.some((x) => x.section_def === s.key && isNonconforming(s, x.values)));
      // 반복 섹션이 없는 양식(D03 v2 등)은 "관련 행" 열을 숨긴다(P6a-S1 DOC-SC-04). 행이 아직 없는 CCP 문서는 열 유지
      const hasRows = schema.sections.some((s) => s.repeat);
      el.innerHTML = `
        <div class="te-section te-deviation" id="teDeviation">
          <div class="te-section-head"><span class="te-section-title">한계기준 이탈·개선조치 <span class="te-hint">문서 상태와 상관없이 언제든 수정·확인할 수 있습니다</span></span>
            <button class="btn btn-secondary btn-sm" id="devAdd" ${mayWrite ? '' : 'disabled'}>+ 추가</button></div>
          ${api.staffId && !mayWrite ? `<div class="te-perm-note" id="devWriteWhy">${esc(T.WRITE_WHY)}${saved.some((x) => (x.checker_ids || []).includes(me)) ? ' 내가 확인자로 지정된 줄은 수정할 수 있습니다.' : ''} ${T.roleLink()}</div>` : ''}
          ${nonconforming && !saved.length ? '<div class="te-error-text">부적합 항목이 있어 작성완료하려면 이탈·개선조치를 1건 이상 적어야 합니다.</div>' : ''}
          <div class="te-table-wrap"><table class="data-table te-rows">
            <thead><tr>${hasRows ? '<th>관련 행</th>' : ''}<th>한계기준 이탈내용 *</th><th>조치자</th><th>개선조치 및 결과</th><th>확인자 <span class="te-hint">(자동 — 담당자 + HACCP팀장)</span></th><th>확인</th><th></th></tr></thead>
            <tbody>${saved.map((x) => line(x, `s${x.deviation_id}`)).join('')}${this.devDrafts.map((x, i) => line(x, `n${i}`)).join('')
              || (saved.length ? '' : `<tr><td colspan="${hasRows ? 7 : 6}" class="te-empty">기록된 개선조치가 없습니다.</td></tr>`)}</tbody>
          </table></div>
          ${saved.some((x) => x.deviation_id && !x.checked_at) ? '<div class="te-hint" id="devLeaderNote">ⓘ HACCP팀장은 확인자 목록과 관계없이 확인할 수 있습니다(확인자 없는 줄도).</div>' : ''}
          ${this.devDrafts.length ? `<div class="te-hint" id="devDefaultNote">ⓘ 확인자는 고르지 않습니다 — 저장할 때 이 양식 담당자 + HACCP팀장으로 자동 지정됩니다(저장 때의 역할 기준).${truncated ? ' 확인자가 많아 10명까지만 지정됩니다(담당자 먼저).' : ''}</div>` : ''}
        </div>`;
      const read = (tr) => {
        const v = (k) => tr.querySelector(`[data-k="${k}"]`);
        const num = (x) => (x === '' ? null : Number(x));
        return {
          section_id: v('section_id') ? num(v('section_id').value) : null, description: v('description').value.trim(),
          actor_id: num(v('actor_id').value), action_result: v('action_result').value.trim() || null,
        };  // r12(D-199): checker_ids는 보내지 않음 — 새 개선조치는 서버가 자동 지정, 저장된 확인자는 그대로
      };
      const reload = () => this.showDetail(d.document_id);
      el.querySelector('#devAdd').addEventListener('click', () => { this.syncDevDrafts(el); this.devDrafts.push({}); this.renderDeviations(d, schema, { synced: true }); });
      el.querySelectorAll('[data-dev-save]').forEach((b) => b.addEventListener('click', async () => {
        const key = b.dataset.devSave;
        const tr = el.querySelector(`tr[data-dev="${key}"]`);
        const body = read(tr);
        let res;
        if (key.startsWith('n')) {
          res = await api.post(`documents/${d.document_id}/deviations`, body);
          if (res.ok) { this.syncDevDrafts(el); this.devDrafts.splice(Number(key.slice(1)), 1); }  // 다른 새 줄 값은 남김
        } else {
          const cur = saved.find((x) => `s${x.deviation_id}` === key);
          const patch = {};
          Object.entries(body).forEach(([k, val]) => { if (JSON.stringify(val) !== JSON.stringify(cur[k] ?? (k === 'checker_ids' ? [] : null))) patch[k] = val; });
          if (!Object.keys(patch).length) { T.toast('바뀐 내용이 없습니다.', 'info'); return; }
          res = await api.patch(`deviations/${cur.deviation_id}`, { expected_version: cur.version, ...patch });
        }
        if (res.ok && res.data && res.data.checker_warning) {
          // r14(D-202 Q5 a): 확인자 기본값 0명 — 저장은 됨, 역할 설정 확인 알림
          const why = res.data.checker_warning === 'config_invalid' ? '역할 설정 파일 오류' : '이 양식에 담당자·HACCP팀장이 없음';
          T.toast(`개선조치를 저장했지만 확인자를 정하지 못했습니다(${why}) — 역할 설정을 확인하세요.`, 'error');
          reload();
          return;
        }
        if (res.ok) { T.toast('개선조치를 저장했습니다.', 'success'); reload(); return; }
        if (res.data && res.data.code === 'VERSION_CONFLICT') { T.toast('다른 사용자가 먼저 이 개선조치를 수정했습니다. 최신 내용으로 다시 불러옵니다.', 'error'); reload(); return; }
        const details = (res.data && res.data.details) || [];
        T.toast(`${T.errorText(res)}${details.length ? ` — ${details.map((x) => x.message).join(' / ')}` : ''}`, 'error');
      }));
      el.querySelectorAll('[data-dev-check]').forEach((b) => b.addEventListener('click', async () => {
        const key = b.dataset.devCheck;
        const cur = saved.find((x) => `s${x.deviation_id}` === key);
        const body = read(el.querySelector(`tr[data-dev="${key}"]`));
        // 편집 중인 값이 있으면 저장 먼저(S1b 5장 — 확인 창에는 저장된 내용이 보여야 함)
        const changed = Object.entries(body).some(([k, val]) => JSON.stringify(val) !== JSON.stringify(cur[k] ?? (k === 'checker_ids' ? [] : null)));
        if (changed) { T.toast('바뀐 내용을 먼저 저장하세요. 확인은 저장된 내용으로 합니다.', 'error'); return; }
        if (!window.TempEntryDashboard) return;
        const result = await window.TempEntryDashboard.confirmCheck({
          deviation_id: cur.deviation_id, version: cur.version, title: `${d.template.name} — 문서 #${d.document_id} (${d.work_date})`,
          description: cur.description, action_result: cur.action_result, actor_id: cur.actor_id,
        });
        if (!result.cancelled) reload();
      }));
      el.querySelectorAll('[data-dev-del]').forEach((b) => b.addEventListener('click', async () => {
        const key = b.dataset.devDel;
        if (key.startsWith('n')) { this.syncDevDrafts(el); this.devDrafts.splice(Number(key.slice(1)), 1); this.renderDeviations(d, schema, { synced: true }); return; }
        const cur = saved.find((x) => `s${x.deviation_id}` === key);
        if (!(await T.confirm('개선조치 삭제', '이 개선조치를 삭제합니다. 기록은 삭제자·시각과 함께 보존됩니다.', '삭제', 'btn-danger'))) return;
        const res = await api.del(`deviations/${cur.deviation_id}?expected_version=${cur.version}`);
        if (res.ok) { T.toast('삭제했습니다.', 'success'); reload(); return; }
        T.toast(T.errorText(res), 'error');
        reload();
      }));
    },

    // ================================================= DOC-SC-09 작성완료 확인·검사 결과
    async confirmComplete(d, schema) {
      let r;
      if (d.template.type_code === 'D03') {
        // ISS-027 ①(P10): 부적합 행이 있는데 개선조치가 없으면 확인 창 없이 서버와 같은 문구로 먼저 막는다
        const nonconforming = schema.sections.some((s) => d.sections.some((x) => x.section_def === s.key && isNonconforming(s, x.values)));
        if (nonconforming && !(d.deviations || []).length) {
          await this.showIncomplete(d, schema, [{ path: 'deviations', code: 'deviation_required', message: '부적합 항목이 있어 이탈·개선조치를 1건 이상 적으세요.' }]);
          return;
        }
        r = await this.completeD03(d, schema);
        if (!r) return; // 취소
      } else {
        const ok = await T.confirm('작성완료', `문서 #${d.document_id}을(를) 작성완료합니다.<br>작성완료 후에는 [작성 재개]를 눌러야 수정할 수 있습니다.`, '작성완료', 'btn-primary te-btn-complete');
        if (!ok) return;
        r = await api.post(`documents/${d.document_id}/complete`, { expected_version: d.version });
      }
      if (r.ok) { T.toast(d.template.type_code === 'D03' ? '작성완료 · 판정 전달' : '작성완료했습니다.', 'success'); this.showDetail(d.document_id); return; }
      const data = r.data || {};
      if (data.code === 'COMPLETION_INCOMPLETE') {
        await this.showIncomplete(d, schema, data.details || []);
        return;
      }
      if (data.code === 'VERSION_CONFLICT') {
        await T.modal({ title: '다른 사용자가 먼저 수정했습니다', body: '<p>최신 내용을 다시 불러옵니다. 확인한 뒤 다시 작성완료하세요.</p>', buttons: [{ label: '확인', value: true, cls: 'btn-primary' }] });
        this.showDetail(d.document_id);
        return;
      }
      T.toast(T.errorText(r), 'error');
      this.showDetail(d.document_id);
    },

    // 작성완료할 수 없음(서버 COMPLETION_INCOMPLETE, 또는 ISS-027 ① 화면 먼저 검사): 채울 항목 + 이동 버튼
    async showIncomplete(d, schema, details) {
      const items = details.map((e) => `<li>${esc(this.problemText(e, schema, d.sections))}</li>`).join('');
      // 이동할 곳: 폼 항목(값·행) → 작성 폼, 개선조치만 → 상세의 개선조치 영역, 파일만 → 상세의 증빙 파일 영역
      const formProblems = details.filter((e) => e.path !== 'deviations' && e.path !== 'files');
      const devProblem = details.some((e) => e.path === 'deviations');
      const fileProblem = details.some((e) => e.path === 'files');
      const buttons = [{ label: '닫기', value: false }];
      if (formProblems.length && EDITABLE.includes(d.status)) buttons.push({ label: '수정하러 가기', value: 'form', cls: 'btn-primary' });
      else if (devProblem) buttons.push({ label: '개선조치 입력하러 가기', value: 'deviation', cls: 'btn-primary' });
      else if (fileProblem) buttons.push({ label: '파일 올리러 가기', value: 'files', cls: 'btn-primary' });
      const go = await T.modal({
        title: '작성완료할 수 없습니다',
        body: `<p>아래 항목을 먼저 채워 주세요.</p><ul class="te-pending" id="teCompleteProblems">${items}</ul>`,
        buttons,
      });
      if (go === 'form') this.openForm({ document: d, problems: details });
      else if (go === 'deviation') this.goToDeviation(d, schema);
      else if (go === 'files') this.root.querySelector('#teFileArea')?.scrollIntoView({ block: 'center' });
    },

    // DOC-SC-09 (D03, P6 + P6a 3.2): LOT 1건의 판정 + 판정 변경 사유(note, 저장하지 않음 — 수불에 전달만).
    // 수불 거부(409 INVENTORY_REJECTED)·연동 없음(503)은 모달을 닫지 않고 위에 빨간 영역. 그 밖의 응답은 호출자로 넘긴다.
    completeD03(d, schema) {
      const section = schema.sections.find((x) => x.key === 'inspection');
      const field = section && section.fields.find((fd) => fd.key === 'verdict');
      const row = d.sections.find((x) => x.section_def === 'inspection');
      const verdict = row && row.values.verdict;
      const lot = (d.refs || []).find((x) => x.lot_id !== null);
      const lotName = lot ? (lot.label || lot.lot_id) : '-';
      const verdictText = verdict ? `${field ? optionLabel(field, verdict) : verdict}(${verdict})` : '(판정 없음)';
      const prefill = d.correction ? d.correction.reason : '';
      return new Promise((resolve) => {
        const wrap = document.createElement('div');
        wrap.className = 'te-modal-wrap';
        wrap.innerHTML = `
          <div class="te-modal" role="dialog" aria-modal="true" id="teD03Complete">
            <div class="modal-header"><div class="modal-title">작성완료 — ${esc(d.template.name)} #${d.document_id} · LOT ${esc(lotName)}</div></div>
            <div class="te-modal-body">
              <div id="d03Reject"></div>
              <p>작성완료하면 판정 <b class="${verdict === 'FAIL' ? 'te-judge-ng' : 'te-judge-ok'}">${esc(verdictText)}</b>이 수불에 전달됩니다.</p>
              <label class="form-label" for="d03Note" style="margin-top:.6rem">판정 변경 사유 (선택, ${REASON_MAX}자)</label>
              <input class="form-control" id="d03Note" maxlength="${REASON_MAX}" value="${esc(prefill)}">
              <div class="te-counter" id="d03Count">${prefill.length}/${REASON_MAX}</div>
              <p class="te-hint">ⓘ 이미 판정된 LOT의 판정을 바꾸면 사유가 필요합니다.${d.correction ? ' 정정 사유를 미리 채웠습니다(지우면 정정 사유가 그대로 쓰입니다).' : ''}</p>
            </div>
            <div class="te-modal-footer">
              <button class="btn btn-secondary" id="d03Close">취소</button>
              <button class="btn btn-primary te-btn-complete" id="d03Go">작성완료</button>
            </div>
          </div>`;
        document.body.appendChild(wrap);
        const $ = (sel) => wrap.querySelector(sel);
        const done = (value) => { wrap.remove(); resolve(value); };
        const note = $('#d03Note');
        note.addEventListener('input', () => { $('#d03Count').textContent = `${note.value.trim().length}/${REASON_MAX}`; });
        $('#d03Close').addEventListener('click', () => done(null));
        $('#d03Go').addEventListener('click', async () => {
          $('#d03Go').disabled = true;
          $('#d03Go').textContent = '처리 중…';
          const body = { expected_version: d.version };
          if (note.value.trim()) body.note = note.value.trim();
          const r = await api.post(`documents/${d.document_id}/complete`, body);
          const code = r.data && r.data.code;
          if (code === 'INVENTORY_REJECTED' || code === 'INVENTORY_NOT_CONFIGURED') {
            const items = (r.data.details || []).map((x) => `<li><b>${esc(x.lot_number || x.lot_id || '')}</b> ${esc(x.message)}</li>`).join('');
            $('#d03Reject').innerHTML = `<div class="te-inv-reject" id="teInvReject">
              <b>⚠ ${code === 'INVENTORY_REJECTED' ? '수불이 판정을 받지 않았습니다' : esc(r.data.message)} — 작성완료하지 않았습니다</b>
              ${items ? `<ul>${items}</ul>` : ''}
              <div class="te-hint">${code === 'INVENTORY_REJECTED' ? '메시지는 수불이 보낸 문구입니다. 사유를 적거나 수불 담당자와 확인하세요.' : '서버 설정(HACCP_INVENTORY_JUDGMENT)을 확인하세요.'}</div></div>`;
            $('#d03Go').disabled = false;
            $('#d03Go').textContent = '작성완료';
            note.focus();
            return;
          }
          done(r);
        });
        note.focus();
      });
    },

    // P11: 대시보드 이탈 줄 [열기] — 개선조치가 없으면 그 행을 관련 행으로 채운 추가 줄을 연 채로(S1-Q2 a, "개선조치 추가"와 같은 문구),
    // 있으면 이탈·개선조치 영역으로 스크롤. 한 번만(다시 그릴 때는 하지 않음)
    applyOpenFocus(d, schema, skipped) {
      const want = this.openFocus;
      this.openFocus = null;
      if (!want || (!want.deviationNew && !want.focus)) return;
      if (want.deviationNew && !skipped && api.staffId && !this.devDrafts.some((x) => x.section_id === want.deviationNew)) {
        let text = '';
        schema.sections.filter((s) => s.repeat).forEach((s) => d.sections.filter((x) => x.section_def === s.key).forEach((x, i) => {
          if (x.section_id === want.deviationNew) text = `${s.label} ${x.values.lot_number || `${i + 1}행`} 부적합`;
        }));
        this.devDrafts.push({ section_id: want.deviationNew, description: text });
        this.renderDeviations(d, schema);
      }
      const area = this.root.querySelector('#teDeviation') || this.root.querySelector('#teDeviationArea');
      if (!area) return;
      area.scrollIntoView({ block: 'center' });
      if (want.deviationNew) area.querySelector("tr[data-dev^='n'] [data-k=description]")?.focus({ preventScroll: true });
    },

    // 개선조치 입력 위치로 이동: 첫 부적합 행을 관련 행으로 한 새 입력 행을 연다
    goToDeviation(d, schema) {
      if (!this.devDrafts.length) {
        let related = null;
        schema.sections.filter((s) => s.repeat).forEach((s) => d.sections.filter((x) => x.section_def === s.key).forEach((x) => {
          if (related === null && isNonconforming(s, x.values)) related = x.section_id;
        }));
        this.devDrafts.push(related ? { section_id: related } : {});
      }
      this.renderDeviations(d, schema);
      const area = this.root.querySelector('#teDeviation');
      area.scrollIntoView({ block: 'center' });
      area.querySelector("tr[data-dev^='n'] [data-k=description]")?.focus({ preventScroll: true });
    },

    async reopen(d) {
      // 확인 없이 작성중으로 돌아간다(P4-S1-Q4)
      const r = await api.post(`documents/${d.document_id}/reopen`, { expected_version: d.version });
      if (r.ok) T.toast(r.data.status === 'correcting' ? '작성을 재개했습니다. 정정 중으로 돌아갔습니다.' : '작성을 재개했습니다. 이제 수정할 수 있습니다.', 'success');
      else T.toast(T.errorText(r), 'error');
      this.showDetail(d.document_id);
    },

    // ================================================= P6 정정 배너 (DOC-SC-04)
    correctionBanner(d, c, effective) {
      const eff = effective
        ? `새로 승인될 때까지 유효한 승인본은 <b>${effective.attempt}회차</b>(${T.fmtDateTime(effective.closed_at)} 승인)입니다.
           <button class="btn btn-secondary btn-sm" id="btnEffective" data-request="${effective.request_id}">유효 승인본 보기</button>`
        : '<span class="te-hint">유효 승인본을 읽지 못했습니다.</span>';
      const cancel = d.status === 'correcting'
        ? `<button class="btn btn-secondary btn-sm" id="btnFixCancel" ${api.staffId && c.cancellable && d.permissions && d.permissions.write ? '' : 'disabled'}
             title="${!c.cancellable ? '수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요' : (!api.staffId ? '현재 사용자를 선택하세요' : (d.permissions && d.permissions.write ? '정정을 취소하고 승인 상태로 되돌립니다' : esc(T.WRITE_WHY)))}">정정 취소</button>`
        : '';
      return `<div class="te-fix-banner" id="teFixBanner">
        <div class="te-fix-head">⚠ 정정 중입니다</div>
        <div>${T.fmtDateTime(c.started_at)} ${T.personHtml(c.started_by)} · 사유: ${esc(c.reason)}</div>
        <div>${eff}</div>
        ${cancel ? `<div class="te-fix-actions">${c.cancellable ? '' : '<span class="te-hint">수정한 내용이 있어 취소할 수 없습니다 — 작성완료 후 재상신하세요</span>'}${cancel}</div>` : ''}
      </div>`;
    },

    // 정정 시작·취소 오류 공통: 다시 열기 안내(DOC-SC-06과 같은 방식)
    async reopenAfter(title, message, d) {
      const again = await T.modal({ title, body: `<p>${message}</p>`, buttons: [{ label: '닫기', value: false }, { label: '최신 내용으로 다시 열기', value: true, cls: 'btn-primary' }] });
      if (again) this.showDetail(d.document_id);
    },

    // ================================================= WF-SC-08 정정 시작 모달
    openCorrection(d, effective) {
      const wrap = document.createElement('div');
      wrap.className = 'te-modal-wrap';
      wrap.innerHTML = `
        <div class="te-modal" role="dialog" aria-modal="true" id="teFixModal">
          <div class="modal-header"><div class="modal-title">정정 시작 · 문서 #${d.document_id} (v${d.version})</div></div>
          <div class="te-modal-body">
            <p>승인된 문서를 다시 열어 고칩니다.</p>
            <ul class="te-pending">
              <li>새로 승인될 때까지 지금 승인본${effective ? `(${effective.attempt}회차)` : ''}이 유효합니다.</li>
              <li>고친 뒤 작성완료 → 결재 상신을 다시 해야 합니다.</li>
            </ul>
            <div id="fixTop"></div>
            <label class="form-label" for="fixReason" style="margin-top:.6rem">정정 사유 *</label>
            <input class="form-control" id="fixReason" maxlength="${REASON_MAX + 50}" placeholder="예: 외포장 판정 오기(부적합 → 적합)">
            <div class="te-counter" id="fixCount">0/${REASON_MAX}</div>
            <div class="te-error-text" id="fixError"></div>
          </div>
          <div class="te-modal-footer">
            <button class="btn btn-secondary" id="fixClose">취소</button>
            <button class="btn btn-warning" id="fixGo" disabled>정정 시작</button>
          </div>
        </div>`;
      document.body.appendChild(wrap);
      const $ = (sel) => wrap.querySelector(sel);
      const close = () => wrap.remove();
      const input = $('#fixReason');
      const check = () => {
        const n = input.value.trim().length;
        $('#fixCount').textContent = `${n}/${REASON_MAX}`;
        $('#fixCount').classList.toggle('te-error-text', n > REASON_MAX);
        $('#fixError').textContent = n === 0 ? '정정 사유를 입력하세요' : (n > REASON_MAX ? `${REASON_MAX}자 이하로 입력하세요` : '');
        $('#fixGo').disabled = !api.staffId || n === 0 || n > REASON_MAX;
      };
      input.addEventListener('input', check);
      $('#fixClose').addEventListener('click', close);
      $('#fixGo').addEventListener('click', async () => {
        $('#fixGo').disabled = true;
        $('#fixGo').textContent = '처리 중…';
        const r = await api.post(`documents/${d.document_id}/correction`, { expected_version: d.version, reason: input.value.trim() });
        if (r.ok) { close(); T.toast('정정을 시작했습니다. 이제 수정할 수 있습니다.', 'success'); this.showDetail(d.document_id); return; }
        $('#fixGo').textContent = '정정 시작';
        const data = r.data || {};
        if (data.code === 'VALIDATION_ERROR') {
          $('#fixError').textContent = (data.details || [])[0]?.message || data.message;
          check();
          $('#fixGo').disabled = false;
          return;
        }
        // P14: 403 ROLE_REQUIRED·409 ROLE_CONFIG_INVALID — 모달 안 오류(다시 눌러도 같은 결과)
        if (data.code === 'ROLE_REQUIRED' || data.code === 'ROLE_CONFIG_INVALID') {
          $('#fixTop').innerHTML = `<div class="te-error-box">[${esc(data.code)}] ${data.code === 'ROLE_REQUIRED' ? '이 양식의 담당자나 HACCP팀장만 정정할 수 있습니다.' : '역할 설정 파일 오류로 정정을 시작할 수 없습니다.'} ${T.roleLink()}</div>`;
          return;
        }
        // 409(다른 사람이 먼저 정정 시작·승인 아님·버전) → 모달 안 [코드] 메시지 + [다시 열기]
        $('#fixTop').innerHTML = `<div class="te-error-box">${esc(T.errorText(r))} <button class="btn btn-secondary btn-sm" id="fixReload">다시 열기</button></div>`;
        $('#fixReload').addEventListener('click', () => { close(); this.showDetail(d.document_id); });
      });
      input.focus();
    },

    // ================================================= WF-SC-10 정정 취소 확인 (D-075)
    async cancelCorrection(d, effective) {
      const ok = await T.modal({
        title: `정정 취소 · 문서 #${d.document_id} (v${d.version})`,
        body: `<p>정정을 취소하고 승인 상태로 되돌립니다.</p>
          <ul class="te-pending"><li>정정 시작 뒤 고친 내용이 없어 지금 승인본${effective ? `(${effective.attempt}회차)` : ''}이 그대로 유효합니다.</li>
          <li>정정 기록은 "취소됨"으로 남습니다(사유 이력 보존).</li></ul>`,
        buttons: [{ label: '닫기', value: false }, { label: '정정 취소', value: true, cls: 'btn-danger' }],
      });
      if (!ok) return;
      const r = await api.post(`documents/${d.document_id}/correction/cancel`, { expected_version: d.version });
      if (r.ok) { T.toast('정정을 취소했습니다. 승인 상태로 돌아갔습니다.', 'success'); this.showDetail(d.document_id); return; }
      const code = r.data && r.data.code;
      const message = code === 'CORRECTION_HAS_CHANGES'
        ? '수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요.'
        : esc(T.errorText(r));
      await this.reopenAfter('정정을 취소할 수 없습니다', `${code === 'CORRECTION_HAS_CHANGES' ? `[${code}] ` : ''}${message}`, d);
    },

    // ================================================= DOC-SC-05 삭제 확인
    // P8 F28 되돌리기: 확인 없이 작성중으로(S1-Q5 a — 작성 재개와 같음)
    async unskip(d) {
      const r = await api.post(`documents/${d.document_id}/unskip`, { expected_version: d.version });
      if (r.ok) { T.toast('작성중으로 되돌렸습니다.', 'success'); this.showDetail(d.document_id); return; }
      T.toast(T.errorText(r), 'error');
      this.showDetail(d.document_id);
    },

    // 같은 주 줄(D10·D12, p8-s1 3장): 월~금 상태 아이콘, 누르면 그날 문서. REQ-A04로 읽음(X-Staff-Id 필요)
    async renderWeekStrip(d) {
      const el = this.root.querySelector('#teWeekStrip');
      if (!el || !api.staffId) return;
      const start = shiftDay(d.work_date, -((new Date(`${d.work_date}T00:00:00Z`).getUTCDay() + 6) % 7));
      const r = await api.get(`periodic-bundles?type_code=${encodeURIComponent(d.template.type_code)}&week_start=${start}`);
      if (!r.ok || !this.root.contains(el)) return;
      const icon = (x) => {
        if (!x) return '–';
        if (x.status === 'skipped') return '⊘';
        return ['completed', 'submitted', 'approved'].includes(x.status) ? '✅' : '▢';
      };
      el.innerHTML = `<span class="te-week-strip">같은 주: ${r.data.days.map((x) => {
        const label = `${WEEKDAY[x.weekday % 7]} ${icon(x.document)}`;
        if (x.document && x.document.document_id === d.document_id) return `<span class="te-day te-day-now">${label} (지금)</span>`;
        if (!x.document) return `<span class="te-day te-hint" title="문서 없음">${label}</span>`;
        return `<a href="#" data-week-doc="${x.document.document_id}" title="${esc(T.STATUS[x.document.status]?.label || x.document.status)}">${label}</a>`;
      }).join('')} <a href="#" id="teWeekOpen">주 묶음 ▸</a></span>`;
      el.querySelectorAll('[data-week-doc]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); this.showDetail(Number(a.dataset.weekDoc)); }));
      el.querySelector('#teWeekOpen').addEventListener('click', (e) => { e.preventDefault(); this.showWeek(d.template.type_code, start, { page: 'list' }); });
    },

    async confirmDelete(d) {
      const ok = await T.confirm('문서 삭제',
        `문서 #${d.document_id} (${esc(d.template.name)}, ${d.work_date})를 삭제합니다.<br>목록에서 사라지지만 기록은 삭제자·삭제 시각과 함께 보존됩니다.${d.requirement === 'periodic' ? '<br>주기 문서입니다. 규칙상 만드는 날이면 다음 주기 생성(명령·[주기 문서 만들기]) 때 다시 만들어집니다 — 작성하지 않는 날이면 [작성 안 함]을 쓰세요.' : ''}`,
        '삭제', 'btn-danger');
      if (!ok) return;
      const r = await api.del(`documents/${d.document_id}`);
      if (r.ok) { T.toast('삭제했습니다.', 'success'); this.showList(); return; }
      await T.modal({ title: '삭제할 수 없습니다', body: `<p>${esc(r.data?.message || T.errorText(r))}</p>`, buttons: [{ label: '확인', value: true, cls: 'btn-primary' }] });
      this.showDetail(d.document_id);
    },
  };

  T.register('doc-box', Doc);  // 예전 temp-doc도 이 화면(TempEntry.PAGE_ALIAS)
  Doc.targetText = targetText;  // WF-SC-04 대상(ISS-018 — 예전 요청은 스냅샷으로 계산)
  window.TempEntryDocument = Doc;
})();
