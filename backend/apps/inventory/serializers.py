"""Model / query result -> JSON-ready dicts for the inventory API.

Quantities go out as decimal strings in the item's base unit ("50", "0.25") next to the unit,
never as e6 integers or floats. Dates are 'YYYY-MM-DD'; datetimes are ISO 8601 with +09:00.
"""

from .quantity import from_e6


def qty(value_e6):
    return None if value_e6 is None else str(from_e6(value_e6))


def iso(value):
    return value.isoformat() if value else None


def staff(obj):
    return {
        "id": obj.pk,
        "staff_code": obj.staff_code,
        "name": obj.name,
        "is_active": obj.is_active,
    }


def supplier(obj):
    return {
        "id": obj.pk,
        "supplier_code": obj.supplier_code,
        "name": obj.name,
        "is_active": obj.is_active,
    }


def item(obj):
    return {
        "id": obj.pk,
        "item_code": obj.item_code,
        "item_type": obj.item_type_id,
        "name": obj.name,
        "base_unit": obj.base_unit,
        "short_code": obj.short_code,
        "unit_weight_mg": obj.unit_weight_mg,
        "shelf_life_months": obj.shelf_life_months,
        "shelf_life_days": obj.shelf_life_days,
        "origin_country": obj.origin_country,
        "food_type": obj.food_type,
        "minimum_stock": qty(obj.minimum_stock_e6),
        "is_active": obj.is_active,
    }


def movement(obj):
    lot = obj.lot
    return {
        "id": obj.pk,
        "lot_id": lot.pk,
        "lot_number": lot.lot_number,
        "movement_type": obj.movement_type_id,
        "movement_name": obj.movement_type.name,
        "quantity": qty(obj.quantity_e6),
        "signed_quantity": qty(obj.quantity_e6 * obj.movement_type.direction),
        "unit": lot.item.base_unit,
        "occurred_at": iso(obj.occurred_at),
        "reason": obj.reason,
        "staff": {"id": obj.staff_id, "name": obj.staff.name},
        "corrects_movement_id": obj.corrects_movement_id,
        "created_at": iso(obj.created_at),
    }


def lot(obj, quantity_e6=None):
    return {
        "id": obj.pk,
        "lot_number": obj.lot_number,
        "lot_kind": obj.lot_kind,
        "status": obj.status,
        "item": {
            "id": obj.item_id,
            "item_code": obj.item.item_code,
            "name": obj.item.name,
            "item_type": obj.item.item_type_id,
            "base_unit": obj.item.base_unit,
        },
        "quantity": qty(quantity_e6),
        "manufactured_date": iso(obj.manufactured_date),
        "expiration_date": iso(obj.expiration_date),
        "created_at": iso(obj.created_at),
    }


def receipt(obj):
    lot_obj = obj.lot
    return {
        "id": obj.pk,
        "lot_id": lot_obj.pk,
        "lot_number": lot_obj.lot_number,
        "lot_status": lot_obj.status,
        "item": {
            "id": lot_obj.item_id,
            "item_code": lot_obj.item.item_code,
            "name": lot_obj.item.name,
            "item_type": lot_obj.item.item_type_id,
        },
        "supplier": {"id": obj.supplier_id, "name": obj.supplier.name},
        "supplier_lot_number": obj.supplier_lot_number,
        "received_date": iso(obj.received_date),
        "quantity": qty(obj.quantity_e6),
        "unit": lot_obj.item.base_unit,
        "manufactured_date": iso(lot_obj.manufactured_date),
        "expiration_date": iso(lot_obj.expiration_date),
        "staff": {"id": obj.staff_id, "name": obj.staff.name},
        "receipt_status": obj.receipt_status,
        "cancelled_at": iso(obj.cancelled_at),
        "cancel_reason": obj.cancel_reason,
        "stock_movement_id": obj.stock_movement_id,
        "created_at": iso(obj.created_at),
    }


def lot_stock(row):
    return {
        "lot_id": row.lot_id,
        "lot_number": row.lot_number,
        "lot_kind": row.lot_kind,
        "status": row.status,
        "item": {
            "id": row.item_id,
            "item_code": row.item_code,
            "name": row.item_name,
            "item_type": row.item_type,
        },
        "quantity": qty(row.quantity_e6),
        "unit": row.base_unit,
        "is_usable": row.is_usable,
        "active_hold_count": row.active_hold_count,
        "manufactured_date": iso(row.manufactured_date),
        "expiration_date": iso(row.expiration_date),
        "days_to_expiry": row.days_to_expiry,
        "received_date": iso(row.received_date),
        "supplier_name": row.supplier_name,
    }


def item_stock(row):
    return {
        "item": {
            "id": row.item_id,
            "item_code": row.item_code,
            "name": row.item_name,
            "item_type": row.item_type,
        },
        "unit": row.base_unit,
        "total": qty(row.total_e6),
        "usable": qty(row.usable_e6),
        "quarantine": qty(row.quarantine_e6),
        "unusable": qty(row.unusable_e6),
        "minimum_stock": qty(row.minimum_stock_e6),
        "below_minimum": row.below_minimum,
        "lot_count": row.lot_count,
        "nearest_expiration": iso(row.nearest_expiration),
    }


def ledger_item(row):
    return {
        "item": {
            "id": row.item_id,
            "item_code": row.item_code,
            "name": row.item_name,
            "item_type": row.item_type,
        },
        "unit": row.base_unit,
        "opening": qty(row.opening_e6),
        "in": qty(row.in_e6),
        "out": qty(row.out_e6),
        "closing": qty(row.closing_e6),
        "lots": [
            {
                "lot_id": lot_row.lot_id,
                "lot_number": lot_row.lot_number,
                "status": lot_row.status,
                "expiration_date": iso(lot_row.expiration_date),
                "opening": qty(lot_row.opening_e6),
                "in": qty(lot_row.in_e6),
                "out": qty(lot_row.out_e6),
                "closing": qty(lot_row.closing_e6),
                "lines": [
                    {
                        "movement_id": line.movement_id,
                        "occurred_at": iso(line.occurred_at),
                        "movement_type": line.movement_code,
                        "movement_name": line.movement_name,
                        "quantity": qty(line.signed_quantity_e6),
                        "balance": qty(line.balance_e6),
                        "reason": line.reason,
                        "staff_name": line.staff_name,
                        "corrects_movement_id": line.corrects_movement_id,
                    }
                    for line in lot_row.lines
                ],
            }
            for lot_row in row.lots
        ],
    }


def batch(obj):
    return {
        "id": obj.pk,
        "batch_number": obj.batch_number,
        "process_type": obj.process_type,
        "status": obj.status,
        "status_name": obj.get_status_display(),
        "item": {
            "id": obj.item_id,
            "item_code": obj.item.item_code,
            "name": obj.item.name,
            "item_type": obj.item.item_type_id,
        },
        "unit": obj.item.base_unit,
        "bom_id": obj.bom_id,
        "planned_date": iso(obj.planned_date),
        "planned_quantity": qty(obj.planned_quantity_e6),
        "manufactured_date": iso(obj.manufactured_date),
        "shift": obj.shift,
        "started_at": iso(obj.started_at),
        "completed_at": iso(obj.completed_at),
        "staff": {"id": obj.staff_id, "name": obj.staff.name},
        "notes": obj.notes,
        "cancelled_at": iso(obj.cancelled_at),
        "cancel_reason": obj.cancel_reason,
        "created_at": iso(obj.created_at),
    }


def _batch_line(row):
    item_obj = row["item"]
    return {
        "lot_id": row["lot_id"],
        "lot_number": row["lot_number"],
        "item": {"id": item_obj.pk, "item_code": item_obj.item_code, "name": item_obj.name},
        "unit": item_obj.base_unit,
        "quantity": qty(row["quantity_e6"]),
        "net_quantity": qty(row["net_quantity_e6"]),
        "stock_movement_id": row["stock_movement_id"],
    }


def batch_detail(summary):
    data = batch(summary["batch"])
    data["usages"] = [
        {"id": row["usage_id"], "bom_line_id": row["bom_line_id"], **_batch_line(row)}
        for row in summary["usages"]
    ]
    data["outputs"] = [
        {"id": row["output_id"], "lot_quantity": qty(row["stock_e6"]), **_batch_line(row)}
        for row in summary["outputs"]
    ]
    check = summary["bom_check"]
    data["bom_check"] = check and {
        "basis": check["basis"],
        "basis_quantity": qty(check["basis_e6"]),
        "lines": [
            {
                "line_no": row["line"].line_no,
                "item": {
                    "id": row["line"].component_item_id,
                    "item_code": row["line"].component_item.item_code,
                    "name": row["line"].component_item.name,
                },
                "unit": row["line"].component_item.base_unit,
                "standard": qty(row["standard_e6"]),
                "actual": qty(row["actual_e6"]),
            }
            for row in check["lines"]
        ],
    }
    return data


def bom(obj, lines):
    return {
        "id": obj.pk,
        "item_id": obj.item_id,
        "version": obj.version,
        "base_quantity": qty(obj.base_quantity_e6),
        "effective_from": iso(obj.effective_from),
        "is_active": obj.is_active,
        "lines": [
            {
                "id": line.pk,
                "line_no": line.line_no,
                "item": {
                    "id": line.component_item_id,
                    "item_code": line.component_item.item_code,
                    "name": line.component_item.name,
                },
                "unit": line.component_item.base_unit,
                "quantity": qty(line.quantity_e6),
                "alternatives": [
                    {
                        "id": alternative.item_id,
                        "item_code": alternative.item.item_code,
                        "name": alternative.item.name,
                        "unit": alternative.item.base_unit,
                    }
                    for alternative in line.alternatives.select_related("item").order_by("id")
                ],
            }
            for line in lines
        ],
    }


def hold(obj):
    return {
        "id": obj.pk,
        "target": "batch" if obj.batch_id else "lot",
        "lot": obj.lot_id
        and {
            "id": obj.lot_id,
            "lot_number": obj.lot.lot_number,
            "item_code": obj.lot.item.item_code,
        },
        "batch": obj.batch_id and {"id": obj.batch_id, "batch_number": obj.batch.batch_number},
        "source_type": obj.source_type_id,
        "source_name": obj.source_type.name,
        "source_document_id": obj.source_document_id,
        "parent_hold_id": obj.parent_hold_id,
        "reason": obj.reason,
        "held_by": {"id": obj.held_by_id, "name": obj.held_by.name},
        "held_at": iso(obj.held_at),
        "is_open": obj.released_at is None,
        "released_by": obj.released_by_id
        and {"id": obj.released_by_id, "name": obj.released_by.name},
        "released_at": iso(obj.released_at),
        "disposition": obj.disposition_id,
        "release_reason": obj.release_reason,
    }


def fefo_pick(lot_obj, take_e6, stock_e6):
    return {
        "lot_id": lot_obj.pk,
        "lot_number": lot_obj.lot_number,
        "expiration_date": iso(lot_obj.expiration_date),
        "take": qty(take_e6),
        "stock": qty(stock_e6),
    }


def ledger_change(row):
    return {
        "movement_id": row.movement_id,
        "lot_id": row.lot_id,
        "lot_number": row.lot_number,
        "item_id": row.item_id,
        "item_code": row.item_code,
        "occurred_at": iso(row.occurred_at),
        "created_at": iso(row.created_at),
        "movement_type": row.movement_code,
        "movement_name": row.movement_name,
        "quantity": qty(row.signed_quantity_e6),
        "reason": row.reason,
        "staff_name": row.staff_name,
        "corrects_movement_id": row.corrects_movement_id,
        "affects": row.affects,
    }
