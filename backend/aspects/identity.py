"""Identity aspect for player identity and appearance management.

This aspect provides:
- Player-chosen display name (synced to Entity.name)
- Full appearance description
- Physical attributes (race, sex, build, height, etc.)
- Custom title/epithet
- Short description for room listings
- Name change history

All identity data is mutable and visible to other entities via inspect.
"""

import logging
import re
import time

from .decorators import player_command
from .handler import lambdaHandler
from .thing import Aspect, Entity, callable

logger = logging.getLogger(__name__)

# Validation constants
MAX_NAME_LENGTH = 50
MIN_NAME_LENGTH = 1
MAX_DESCRIPTION_LENGTH = 1000
MAX_SHORT_DESCRIPTION_LENGTH = 100
MAX_TITLE_LENGTH = 50
MAX_ATTRIBUTE_KEY_LENGTH = 30
MAX_ATTRIBUTE_VALUE_LENGTH = 100
MAX_ATTRIBUTES = 20
MAX_NAME_HISTORY = 100
MAX_EQUIPMENT_SUMMARY_LENGTH = 500


class Identity(Aspect):
    """Aspect managing player identity and appearance.
    
    Stores: display_name, title, short_description, description, attributes,
    equipment_summary, name_history, created_at, updated_at.
    """
    
    _tableName = "LOCATION_TABLE"  # Shared aspect table — keyed by entity UUID
    
    def _ensure_identity(self) -> None:
        """Initialize default identity data if not already present."""
        if self.data.get("created_at"):
            return  # Already initialized
        
        now = int(time.time())
        self.data.setdefault("display_name", "")
        self.data.setdefault("title", "")
        self.data.setdefault("short_description", "")
        self.data.setdefault("description", "")
        self.data.setdefault("attributes", {})
        self.data.setdefault("equipment_summary", "")
        self.data.setdefault("name_history", [])
        self.data.setdefault("created_at", now)
        self.data.setdefault("updated_at", now)
        
        # If entity has a name from JWT claims, seed display_name
        entity_name = self.entity.name if self.entity else ""
        if entity_name and not self.data.get("display_name"):
            self.data["display_name"] = entity_name
    
    def _load(self, key=None):
        """Load the aspect and ensure identity is initialized."""
        result = super()._load(key)
        self._ensure_identity()
        return result
    
    @player_command
    def name(self, display_name: str = "") -> dict:
        """Set your display name. This name appears in all communication and events."""
        if not display_name:
            return {"type": "error", "message": "Name cannot be empty."}
        
        display_name = display_name.strip()
        if not display_name:
            return {"type": "error", "message": "Name cannot be empty."}
        if len(display_name) > MAX_NAME_LENGTH:
            return {"type": "error", "message": f"Name must be {MAX_NAME_LENGTH} characters or fewer."}
        if len(display_name) < MIN_NAME_LENGTH:
            return {"type": "error", "message": f"Name must be at least {MIN_NAME_LENGTH} character."}
        
        now = int(time.time())
        old_name = self.entity.name
        
        # Record in name history
        history = self.data.get("name_history", [])
        history.append({
            "old_name": old_name,
            "new_name": display_name,
            "timestamp": now,
            "reason": "player_command",
        })
        # Cap history at 100 entries (FIFO)
        if len(history) > MAX_NAME_HISTORY:
            history = history[-MAX_NAME_HISTORY:]
        self.data["name_history"] = history
        
        # Update Identity aspect
        self.data["display_name"] = display_name
        self.data["updated_at"] = now
        if not self.data.get("created_at"):
            self.data["created_at"] = now
        
        # Sync to Entity.name FIRST (broadcasts depend on this)
        self.entity.name = display_name
        self.entity._save()
        
        # Save Identity aspect
        self._save()
        
        # Broadcast name change to location
        location_uuid = self.entity.location
        if location_uuid:
            self.entity.broadcast_to_location(
                location_uuid,
                {
                    "type": "name_changed",
                    "old_name": old_name,
                    "new_name": display_name,
                    "actor_uuid": self.entity.uuid,
                    "message": f"{old_name} is now known as {display_name}.",
                },
            )
        
        return {
            "type": "name_changed",
            "old_name": old_name,
            "new_name": display_name,
            "message": f"You are now known as {display_name}.",
        }
    
    @player_command
    def describe(self, description: str = "") -> dict:
        """Set your full appearance description visible to anyone who inspects you."""
        if not description:
            return {"type": "error", "message": "Describe yourself as what? Provide a description."}
        
        description = description[:MAX_DESCRIPTION_LENGTH]
        self.data["description"] = description
        self.data["updated_at"] = int(time.time())
        if not self.data.get("created_at"):
            self.data["created_at"] = self.data["updated_at"]
        self._save()
        
        # Truncate for confirmation display
        preview = description[:200] + "..." if len(description) > 200 else description
        
        return {
            "type": "description_updated",
            "description": description,
            "message": f"Your description is now: {preview}",
        }
    
    @player_command
    def appearance(self, attribute: str = "", value: str = "") -> dict:
        """Set or view your physical attributes (race, sex, build, height, etc.)."""
        attributes = self.data.get("attributes", {})
        
        # No arguments: list current attributes
        if not attribute:
            if not attributes:
                return {
                    "type": "appearance",
                    "attributes": {},
                    "message": "You have no physical attributes set. Use: appearance <attribute> <value>",
                }
            
            lines = ["=== Your Appearance ==="]
            for key, val in sorted(attributes.items()):
                lines.append(f"  {key}: {val}")
            lines.append(f"({len(attributes)} attributes set)")
            
            return {
                "type": "appearance",
                "attributes": attributes,
                "message": "\n".join(lines),
            }
        
        # Validate attribute key
        attribute = attribute.lower().strip()
        if not re.match(r'^[a-z][a-z0-9_]{0,29}$', attribute):
            return {
                "type": "error",
                "message": "Attribute name must be 1-30 lowercase letters, numbers, or underscores, starting with a letter.",
            }
        
        # Clear attribute if no value
        if not value:
            if attribute in attributes:
                del attributes[attribute]
                self.data["attributes"] = attributes
                self.data["updated_at"] = int(time.time())
                self._save()
                return {
                    "type": "appearance_updated",
                    "attribute": attribute,
                    "value": "",
                    "attributes": attributes,
                    "message": f"Cleared attribute: {attribute}",
                }
            else:
                return {
                    "type": "error",
                    "message": f"You don't have an attribute called '{attribute}'.",
                }
        
        # Cap at 20 attributes
        if attribute not in attributes and len(attributes) >= MAX_ATTRIBUTES:
            return {
                "type": "error",
                "message": f"You have reached the maximum of {MAX_ATTRIBUTES} attributes. Remove one first.",
            }
        
        # Set the attribute
        value = value.strip()[:MAX_ATTRIBUTE_VALUE_LENGTH]
        attributes[attribute] = value
        self.data["attributes"] = attributes
        self.data["updated_at"] = int(time.time())
        if not self.data.get("created_at"):
            self.data["created_at"] = self.data["updated_at"]
        self._save()
        
        return {
            "type": "appearance_updated",
            "attribute": attribute,
            "value": value,
            "attributes": attributes,
            "message": f"Set {attribute}: {value}",
        }
    
    @player_command
    def shortdesc(self, short_description: str = "") -> dict:
        """Set your short description for room listings."""
        if not short_description:
            return {"type": "error", "message": "Short description cannot be empty."}
        
        short_description = short_description.strip()[:MAX_SHORT_DESCRIPTION_LENGTH]
        self.data["short_description"] = short_description
        self.data["updated_at"] = int(time.time())
        if not self.data.get("created_at"):
            self.data["created_at"] = self.data["updated_at"]
        self._save()
        
        return {
            "type": "shortdesc_updated",
            "short_description": short_description,
            "message": f"Your short description is now: {short_description}",
        }
    
    @player_command
    def inspect(self, entity_uuid: str = "") -> dict:
        """View another entity's identity -- name, description, attributes, and title."""
        if not entity_uuid:
            return {"type": "error", "message": "Inspect whom? Provide an entity UUID."}
        
        # Self-inspection redirects to profile
        if entity_uuid == self.entity.uuid:
            return self.profile()
        
        # Load target entity
        try:
            target_entity = Entity(uuid=entity_uuid)
        except KeyError:
            return {"type": "error", "message": "That entity doesn't exist."}
        
        # Must be at the same location
        if target_entity.location != self.entity.location:
            return {"type": "error", "message": "You can't see that entity from here."}
        
        # Attempt to load target's Identity aspect
        target_name = target_entity.name
        target_title = ""
        target_short = ""
        target_desc = ""
        target_attrs = {}
        target_equip = ""
        has_identity = False
        
        try:
            target_identity = target_entity.aspect("Identity")
            has_identity = True
            target_name = target_identity.data.get("display_name", "") or target_name
            target_title = target_identity.data.get("title", "")
            target_short = target_identity.data.get("short_description", "")
            target_desc = target_identity.data.get("description", "")
            target_attrs = target_identity.data.get("attributes", {})
            target_equip = target_identity.data.get("equipment_summary", "")
        except (ValueError, KeyError):
            # Entity exists but has no Identity aspect -- return basic info
            pass
        
        # Build display name with title
        display = target_name
        if target_title:
            display = f"{target_name} {target_title}"
        
        # Build formatted output
        lines = [f"=== {display} ==="]
        
        if target_short:
            lines.append(target_short)
            lines.append("")
        
        if target_desc:
            lines.append(target_desc)
            lines.append("")
        elif not has_identity:
            lines.append("(No description available.)")
            lines.append("")
        
        if target_attrs:
            lines.append("Physical attributes:")
            for key, val in sorted(target_attrs.items()):
                lines.append(f"  {key}: {val}")
            lines.append("")
        
        if target_equip:
            lines.append("Equipment:")
            lines.append(f"  {target_equip}")
            lines.append("")
        
        lines.append(f"[UUID: {entity_uuid}]")
        
        return {
            "type": "inspect",
            "entity_uuid": entity_uuid,
            "name": target_name,
            "title": target_title,
            "short_description": target_short,
            "description": target_desc,
            "attributes": target_attrs,
            "equipment_summary": target_equip,
            "message": "\n".join(lines),
        }
    
    @player_command
    def profile(self) -> dict:
        """View your own complete identity profile."""
        display_name = self.data.get("display_name", "") or self.entity.name
        title = self.data.get("title", "")
        short_desc = self.data.get("short_description", "")
        description = self.data.get("description", "")
        attributes = self.data.get("attributes", {})
        equipment_summary = self.data.get("equipment_summary", "")
        name_history = self.data.get("name_history", [])
        created_at = self.data.get("created_at", 0)
        updated_at = self.data.get("updated_at", 0)
        
        # Self-heal: sync Entity.name if out of sync
        if self.data.get("display_name") and self.entity.name != self.data["display_name"]:
            self.entity.name = self.data["display_name"]
            self.entity._save()
        
        # Build display name with title
        display = display_name
        if title:
            display = f"{display_name} {title}"
        
        # Format timestamps
        created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(created_at)) if created_at else "Not set"
        updated_str = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(updated_at)) if updated_at else "Never"
        
        # Build output
        lines = [f"=== Your Profile: {display} ==="]
        
        if short_desc:
            lines.append(f"Summary: {short_desc}")
        
        if description:
            lines.append("")
            lines.append("Description:")
            lines.append(description)
        else:
            lines.append("")
            lines.append("Description: (Not set. Use 'describe' to set your appearance.)")
        
        lines.append("")
        if attributes:
            lines.append("Physical attributes:")
            for key, val in sorted(attributes.items()):
                lines.append(f"  {key}: {val}")
        else:
            lines.append("Physical attributes: (None set. Use 'appearance' to set attributes.)")
        
        if equipment_summary:
            lines.append("")
            lines.append(f"Equipment: {equipment_summary}")
        
        lines.append("")
        lines.append(f"Name changes: {len(name_history)}")
        lines.append(f"Identity created: {created_str}")
        lines.append(f"Last updated: {updated_str}")
        lines.append(f"[UUID: {self.entity.uuid}]")
        
        return {
            "type": "profile",
            "name": display_name,
            "title": title,
            "short_description": short_desc,
            "description": description,
            "attributes": attributes,
            "equipment_summary": equipment_summary,
            "name_changes": len(name_history),
            "created_at": created_at,
            "updated_at": updated_at,
            "message": "\n".join(lines),
        }
    
    @player_command
    def title(self, title_text: str = "") -> dict:
        """Set a custom title or epithet that appears after your name."""
        display_name = self.data.get("display_name", "") or self.entity.name
        
        if not title_text:
            # Clear the title
            self.data["title"] = ""
            self.data["updated_at"] = int(time.time())
            self._save()
            return {
                "type": "title_updated",
                "title": "",
                "full_display": display_name,
                "message": f"Title cleared. You are now simply {display_name}.",
            }
        
        title_text = title_text.strip()[:MAX_TITLE_LENGTH]
        self.data["title"] = title_text
        self.data["updated_at"] = int(time.time())
        if not self.data.get("created_at"):
            self.data["created_at"] = self.data["updated_at"]
        self._save()
        
        full_display = f"{display_name} {title_text}"
        
        return {
            "type": "title_updated",
            "title": title_text,
            "full_display": full_display,
            "message": f"You are now {full_display}.",
        }
    
    @callable
    def _sync_entity_name(self, display_name: str = "") -> dict:
        """Sync the Identity display_name to Entity.name."""
        name_to_sync = display_name or self.data.get("display_name", "")
        if not name_to_sync:
            return {"status": "no_name", "message": "No display name to sync."}
        
        if self.entity.name != name_to_sync:
            self.entity.name = name_to_sync
            self.entity._save()
            return {"status": "synced", "name": name_to_sync}
        
        return {"status": "already_synced", "name": name_to_sync}
    
    @callable
    def on_equipment_change(self, equipment_summary: str = "", equipped_items: list = None) -> dict:
        """Update the visible equipment summary when gear changes.
        
        Called by Equipment aspect after equip/unequip operations.
        """
        equipped_items = equipped_items or []
        
        self.data["equipment_summary"] = equipment_summary[:MAX_EQUIPMENT_SUMMARY_LENGTH] if equipment_summary else ""
        self.data["equipped_items"] = equipped_items[:7]  # Max 7 slots
        self.data["updated_at"] = int(time.time())
        self._save()
        
        return {
            "status": "updated",
            "equipment_summary": self.data["equipment_summary"],
        }


handler = lambdaHandler(Entity)