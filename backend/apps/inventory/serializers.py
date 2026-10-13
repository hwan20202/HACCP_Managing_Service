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
