/* 품목당 활성 BOM 은 0개 또는 1개.
   활성 = 새 생산계획에 자동 적용되는 기본 버전. 이전 버전을 쓰는 기존 생산지시는 bom_id 로 고정되므로
   비활성이어도 그대로 진행된다. 0010 이 기존 중복 활성 데이터를 먼저 정리한다. */
CREATE UNIQUE INDEX ux_boms_one_active_per_item ON boms (item_id) WHERE is_active = 1;
