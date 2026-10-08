// =============================================
// BIODOT HACCP - 단위 변환 유틸리티 (완전판)
// UnitConverter: kg↔g, L↔ml 자유 변환
// =============================================

const UnitConverter = {

  // 변환 그룹 정의
  groups: {
    weight: ['kg', 'g'],
    volume: ['L', 'ml'],
    count:  ['개', '박스', '롤', '장'],
    time:   ['sec', 'min'],
  },

  // 단위별 그룹 인덱스
  unitToGroup: {
    'kg': 'weight', 'g': 'weight',
    'L':  'volume', 'ml': 'volume', 'mL': 'volume',
    '개': 'count',  '박스': 'count', '롤': 'count', '장': 'count',
    '포': 'count',
    'sec':'time',   'min': 'time',
  },

  // 기본 단위로 환산 (중간 단위: g, ml)
  toBase: {
    'kg':  v => v * 1000,
    'g':   v => v,
    'L':   v => v * 1000,
    'ml':  v => v,
    'mL':  v => v,
    'sec': v => v,
    'min': v => v * 60,
  },

  // 기본 단위에서 변환
  fromBase: {
    'kg':  v => v / 1000,
    'g':   v => v,
    'L':   v => v / 1000,
    'ml':  v => v,
    'sec': v => v,
    'min': v => v / 60,
  },

  // 단위 변환 (fromUnit → toUnit)
  convert(value, fromUnit, toUnit) {
    if (fromUnit === toUnit) return value;
    const base = (this.toBase[fromUnit] || (v => v))(value);
    const result = (this.fromBase[toUnit] || (v => v))(base);
    return Math.round(result * 10000) / 10000; // 소수점 4자리
  },

  // 같은 그룹의 다음 단위 반환 (토글)
  nextUnit(unit) {
    const group = this.unitToGroup[unit];
    if (!group) return unit;
    const arr = this.groups[group].filter(u => this.toBase[u]);
    const idx = arr.indexOf(unit);
    if (idx === -1 || arr.length < 2) return unit;
    return arr[(idx + 1) % arr.length];
  },

  // 변환 가능 여부
  canConvert(unit) {
    const group = this.unitToGroup[unit];
    if (!group) return false;
    const arr = this.groups[group].filter(u => this.toBase[u]);
    return arr.length > 1;
  },

  // 숫자 표시 포맷 (4자리 이상 천단위 콤마)
  format(value, unit) {
    if (value === null || value === undefined) return '-';
    const n = parseFloat(value);
    if (isNaN(n)) return String(value);
    let str;
    if (unit === 'g' || unit === 'ml' || unit === '개' || unit === '장' || unit === '포') {
      str = Number.isInteger(n) ? n.toLocaleString() : n.toFixed(1);
    } else if (unit === 'kg' || unit === 'L') {
      str = n % 1 === 0 ? n.toLocaleString() : parseFloat(n.toFixed(3)).toLocaleString();
    } else {
      str = n % 1 === 0 ? n.toLocaleString() : parseFloat(n.toFixed(2)).toLocaleString();
    }
    return str;
  },

  // ── 핵심 UI ──────────────────────────────

  /**
   * 클릭 가능한 단위 배지 HTML
   * 클릭 시 값+단위가 즉시 변환되며 토스트 알림
   */
  renderToggleBadge(value, unit, context = '', extraStyle = '') {
    const can  = this.canConvert(unit);
    const next = this.nextUnit(unit);
    const displayVal = this.format(value, unit);

    if (!can) {
      return `<span class="unit-badge unit-fixed" style="${extraStyle}">
        <span class="unit-val">${displayVal}</span>
        <span class="unit-label">${unit}</span>
      </span>`;
    }

    return `<span class="unit-badge unit-toggle"
        data-value="${value}"
        data-unit="${unit}"
        data-next="${next}"
        data-ctx="${context}"
        style="${extraStyle}"
        onclick="UnitConverter.handleToggle(this)"
        title="${unit} → ${next} 클릭하여 변환">
      <span class="unit-val">${displayVal}</span>
      <span class="unit-label">${unit}</span>
      <span class="unit-switch-icon">⇄</span>
    </span>`;
  },

  // 토글 클릭 핸들러
  handleToggle(el) {
    const val  = parseFloat(el.dataset.value);
    const unit = el.dataset.unit;
    const next = el.dataset.next;

    const converted = this.convert(val, unit, next);
    const newNext   = this.nextUnit(next);

    el.dataset.value = converted;
    el.dataset.unit  = next;
    el.dataset.next  = newNext;

    el.querySelector('.unit-val').textContent   = this.format(converted, next);
    el.querySelector('.unit-label').textContent = next;
    el.title = `${next} → ${newNext} 클릭하여 변환`;

    // 시각 피드백
    el.classList.add('unit-flash');
    setTimeout(() => el.classList.remove('unit-flash'), 400);

    // 토스트
    if (typeof App !== 'undefined') {
      App.showToast('info', '단위 변환', `${this.format(val,unit)} ${unit} → ${this.format(converted,next)} ${next}`);
    }
  },

  /**
   * 수불대장 행: 수량 + 단위 + 규격을 한 셀에 묶어 렌더
   * spec: 규격 문자열 (예: "식품원료", "PP백 등")
   */
  renderLedgerCell(value, unit, spec = '', context = '') {
    const badge = this.renderToggleBadge(value, unit, context);
    return `
      <div class="ledger-qty-cell">
        ${badge}
        ${spec ? `<div class="ledger-spec" title="${spec}">${spec}</div>` : ''}
      </div>`;
  },

  /**
   * 현재고 셀 렌더 (재고량 + 단위 토글 + 최솟값 표시)
   */
  renderStockCell(balance, unit, minStock = null) {
    const badge = this.renderToggleBadge(balance, unit);
    const isLow = minStock !== null && balance <= minStock * 1.5;
    return `
      <div class="stock-qty-cell ${isLow ? 'stock-low' : ''}">
        ${badge}
        ${minStock !== null ? `<div class="stock-min-label">최소 ${this.format(minStock, unit)} ${unit}</div>` : ''}
      </div>`;
  },
};
