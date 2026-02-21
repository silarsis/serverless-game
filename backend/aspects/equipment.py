"""Equipment aspect.

Implements Feature 05 (Equipment): fixed gear slots, equip/unequip/gear commands,
with cached stat bonuses.

Design note: this aspect uses DynamoDB batch_get_item (via aws_client helper)
when computing gear display / bonuses, to avoid per-slot reads.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from aspects.aws_client import dynamodb_batch_get_by_uuid
from aspects.decorators import callable, player_command
from aspects.thing import Aspect, Entity

SLOTS: Dict[str, Dict[str, str]] = {
    "head": {"name": "Head", "description": "Helmets, hats, crowns"},
    "body": {"name": "Body", "description": "Armor, robes, cloaks"},
    "hands": {"name": "Hands", "description": "Gloves, gauntlets"},
    "feet": {"name": "Feet", "description": "Boots, shoes, greaves"},
    "held_main": {"name": "Main Hand", "description": "Weapons, staves, wands"},
    "held_off": {"name": "Off Hand", "description": "Shields, secondary weapons"},
    "accessory": {"name": "Accessory", "description": "Rings, amulets, charms"},
}


def _slot_label(slot: str) -> str:
    return SLOTS.get(slot, {}).get("name", slot)


class Equipment(Aspect):
    """Equipment aspect (stored in LOCATION_TABLE keyed by entity uuid)."""

    _tableName = "LOCATION_TABLE"  # Shared aspect table

    def _ensure_defaults(self) -> None:
        self.data.setdefault("uuid", self.entity.uuid if self.entity else self.uuid)
        self.data.setdefault("equipped", {})
        self.data.setdefault("stat_bonuses", {"attack": 0, "defense": 0, "magic": 0, "hp": 0})
        self.data.setdefault("stat_bonuses_computed_at", 0)

    def _get_equipped(self) -> Dict[str, str]:
        self._ensure_defaults()
        equipped = self.data.get("equipped", {}) or {}
        return {str(k): str(v) for k, v in equipped.items() if v}

    def _recompute_bonuses(self) -> Dict[str, int]:
        """Recompute and cache aggregate bonuses for all equipped items."""
        equipped = self._get_equipped()
        uuids = list({u for u in equipped.values() if u})

        totals = {"attack": 0, "defense": 0, "magic": 0, "hp": 0}
        if not uuids:
            self.data["stat_bonuses"] = totals
            self.data["stat_bonuses_computed_at"] = int(time.time())
            return totals

        _ = dynamodb_batch_get_by_uuid("ENTITY_TABLE", uuids)
        entity_items = {i.get("uuid"): i for i in dynamodb_batch_get_by_uuid("ENTITY_TABLE", uuids)}
        inv_items = {i.get("uuid"): i for i in dynamodb_batch_get_by_uuid("LOCATION_TABLE", uuids)}

        for item_uuid in uuids:
            inv = inv_items.get(item_uuid, {})
            durability = inv.get("durability", 100)

            attack = int(inv.get("attack_bonus", 0) or 0)
            defense = int(inv.get("defense_bonus", 0) or 0)
            magic = int(inv.get("magic_bonus", 0) or 0)
            hp = int(inv.get("hp_bonus", 0) or 0)

            if durability <= 0:
                attack //= 2
                defense //= 2
                magic //= 2
                hp //= 2

            totals["attack"] += attack
            totals["defense"] += defense
            totals["magic"] += magic
            totals["hp"] += hp

        self.data["stat_bonuses"] = totals
        self.data["stat_bonuses_computed_at"] = int(time.time())
        return totals

    def _item_in_inventory(self, item_entity: Entity) -> bool:
        return item_entity.data.get("location") == self.entity.uuid

    @player_command
    def gear(self) -> dict:
        equipped = self._get_equipped()
        uuids = list({u for u in equipped.values() if u})

        slots_out: Dict[str, Optional[dict]] = {slot: None for slot in SLOTS}
        if uuids:
            entity_items = {
                i.get("uuid"): i for i in dynamodb_batch_get_by_uuid("ENTITY_TABLE", uuids)
            }
            inv_items = {
                i.get("uuid"): i for i in dynamodb_batch_get_by_uuid("LOCATION_TABLE", uuids)
            }

            for slot, item_uuid in equipped.items():
                ent = entity_items.get(item_uuid, {})
                inv = inv_items.get(item_uuid, {})
                if not ent:
                    continue
                slots_out[slot] = {
                    "uuid": item_uuid,
                    "name": ent.get("name", "(unknown)"),
                    "slot": inv.get("slot", slot),
                    "attack_bonus": int(inv.get("attack_bonus", 0) or 0),
                    "defense_bonus": int(inv.get("defense_bonus", 0) or 0),
                    "magic_bonus": int(inv.get("magic_bonus", 0) or 0),
                    "hp_bonus": int(inv.get("hp_bonus", 0) or 0),
                    "durability": int(inv.get("durability", 100) or 0),
                }

        totals = self.data.get("stat_bonuses")
        if not totals:
            totals = self._recompute_bonuses()

        return {"type": "gear", "slots": slots_out, "total_bonuses": totals}

    @player_command
    def equip(self, item_uuid: str = "") -> dict:
        if not item_uuid:
            return {"type": "error", "message": "Equip what? Provide an item uuid."}

        try:
            item = Entity(uuid=item_uuid)
        except Exception:
            return {"type": "error", "message": "Item not found."}

        if not self._item_in_inventory(item):
            return {"type": "error", "message": "You are not carrying that item."}

        try:
            inv = item.aspect("Inventory")
        except Exception:
            return {"type": "error", "message": "Item has no Inventory data."}

        slot = (inv.data.get("slot") or "").strip()
        if not slot:
            return {"type": "error", "message": "That item cannot be equipped."}
        if slot not in SLOTS:
            return {"type": "error", "message": f"Invalid slot on item: {slot}"}

        level_required = int(inv.data.get("level_required", 0) or 0)
        if level_required:
            return {
                "type": "error",
                "message": "Level requirements are not yet implemented for equipment.",
            }

        equipped = self._get_equipped()
        prev_uuid = equipped.get(slot)
        equipped[slot] = item_uuid
        self.data["equipped"] = equipped

        before = self.data.get("stat_bonuses", {"attack": 0, "defense": 0, "magic": 0, "hp": 0})
        after = self._recompute_bonuses()
        self.data["updated_at"] = int(time.time())
        self._save()

        stat_changes = {
            k: (after.get(k, 0) - before.get(k, 0))
            for k in ("attack", "defense", "magic", "hp")
            if after.get(k, 0) != before.get(k, 0)
        }

        msg = f"You equip the {item.name} in your {_slot_label(slot).lower()}."
        if prev_uuid and prev_uuid != item_uuid:
            msg = f"You equip the {item.name} in your {_slot_label(slot).lower()}, replacing what was there."

        return {
            "type": "equip_confirm",
            "item": item.name,
            "slot": slot,
            "stat_changes": stat_changes,
            "message": msg,
        }

    @player_command
    def unequip(self, slot: str = "") -> dict:
        slot = (slot or "").strip()
        if not slot:
            return {"type": "error", "message": "Unequip what? Provide a slot name."}
        if slot not in SLOTS:
            return {"type": "error", "message": f"Unknown slot: {slot}"}

        equipped = self._get_equipped()
        item_uuid = equipped.get(slot)
        if not item_uuid:
            return {"type": "error", "message": f"Nothing is equipped in {_slot_label(slot)}."}

        try:
            item = Entity(uuid=item_uuid)
            item_name = item.name
        except Exception:
            item_name = "(unknown item)"

        before = self.data.get("stat_bonuses", {"attack": 0, "defense": 0, "magic": 0, "hp": 0})

        equipped.pop(slot, None)
        self.data["equipped"] = equipped
        after = self._recompute_bonuses()
        self.data["updated_at"] = int(time.time())
        self._save()

        stat_changes = {
            k: (after.get(k, 0) - before.get(k, 0))
            for k in ("attack", "defense", "magic", "hp")
            if after.get(k, 0) != before.get(k, 0)
        }

        return {
            "type": "unequip_confirm",
            "item": item_name,
            "slot": slot,
            "stat_changes": stat_changes,
            "message": f"You remove the {item_name} from your {_slot_label(slot).lower()}.",
        }

    @callable
    def get_stat_bonuses(self) -> dict:
        totals = self.data.get("stat_bonuses")
        if not totals:
            totals = self._recompute_bonuses()
            self._save()
        return {"bonuses": totals}

    @callable
    def degrade_durability(self, slot: str, amount: int = 1) -> dict:
        slot = (slot or "").strip()
        if slot not in SLOTS:
            return {"status": "error", "message": f"Unknown slot: {slot}"}

        equipped = self._get_equipped()
        item_uuid = equipped.get(slot)
        if not item_uuid:
            return {"status": "noop", "message": "No item equipped"}

        item = Entity(uuid=item_uuid)
        inv = item.aspect("Inventory")
        durability = int(inv.data.get("durability", 100) or 0)
        durability -= int(amount or 1)
        inv.data["durability"] = durability
        inv.data["updated_at"] = int(time.time())
        inv._save()

        self._recompute_bonuses()
        self._save()

        if durability <= 0:
            return {
                "status": "broken",
                "slot": slot,
                "item_uuid": item_uuid,
                "message": f"Your {item.name} breaks! Its bonuses are reduced.",
            }

        return {
            "status": "degraded",
            "slot": slot,
            "item_uuid": item_uuid,
            "durability": durability,
        }
