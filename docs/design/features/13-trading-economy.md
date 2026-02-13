# Trading/Economy Aspect

## What This Brings to the World

An economy is the connective tissue that gives every other system in the game a reason to exist. Without trading and currency, crafting produces items that accumulate without purpose, combat yields loot that piles up, merchants are decorative NPCs with no function, and the entire game is a hoarding simulator. With an economy, a crafted sword has a price. A goblin drops gold. A merchant in the settlement sells healing herbs that the player actually needs. Suddenly every item has two values: its use value (what it does for you) and its exchange value (what someone else will pay). That duality creates decisions -- do I keep this rare sword or sell it for 200 gold to buy three potions instead? Decisions are gameplay.

Player-to-player trading adds a social dimension that no NPC system can replicate. When two players negotiate a trade, they are engaged in genuine human interaction -- bluffing, bargaining, assessing what the other person wants. A player who has been farming leather in the forest can trade with a player who has been mining ore in the mountains, and both come away richer than they started. This kind of emergent cooperation is the beating heart of multiplayer games, and it requires exactly zero content creation from the developers.

For this architecture, the economy is a mixed fit. The currency-as-entity model (gold is an item with a stack_count) reuses the existing Inventory system elegantly -- no new tables, no new data model, just an item with a special tag. Merchant buy/sell operations are simple reads and writes to existing entities. The dangerous parts are the player-to-player trade state machine (which has no atomicity guarantees) and the read-modify-write pattern on stack_count (which is a race condition under concurrent access). This system is a critical enabler -- Crafting needs a market for outputs, Dialogue needs merchants with prices, Faction needs price modifiers -- but it is also the first system that exposes the fundamental limitation of last-write-wins in a multiplayer economy.

## Critical Analysis

**Gold stack_count modification is a read-modify-write race condition.** When a player buys from a merchant, the Trading aspect reads the player's gold entity, reads its Inventory aspect to get `stack_count`, subtracts the price, and writes back with `put_item`. If the player simultaneously buys from two different merchants (two Lambda invocations), both read the same `stack_count` (say, 500), both subtract their prices (100 and 200), and both write back. The second write wins: the player ends up with either 400 or 300 gold instead of the correct 200. The player effectively gets one item for free. There are no DynamoDB conditional writes or transactions in the codebase. This is the single most exploitable bug in the economy and it exists from day one.

**Player-to-player trade is NOT atomic -- crash mid-trade means partial transfer.** The `accept` command iterates through offered items and moves each one individually by setting `item_entity.location = other_player.uuid`. If the Lambda crashes after moving 2 of 4 items, those 2 items are gone from the original player's inventory and in the other player's inventory, but the remaining 2 items and the gold payment never transferred. There is no rollback mechanism, no transaction log, and no way to detect that a trade was partially completed. The only evidence is that two players have unexpected inventories. Escrow would fix this but requires an intermediate entity to hold items, adding complexity and write costs.

**No escrow mechanism means offered items can be dropped or destroyed mid-trade.** When a player uses `offer <item_uuid>`, the item stays in their inventory. The trade_state records the item UUID but does not lock or move the item. Between offering and accepting, the player (or another concurrent Lambda invocation) can `drop` the item, use it as a crafting ingredient, or even `destroy` it. When `accept` fires, it tries to move an item that no longer exists or is no longer in the player's inventory. The accept command must re-validate every offered item at execution time, and if any are missing, the entire trade should fail -- but this validation-then-act sequence is itself a race condition (item could be dropped between validation and transfer).

**Trade state stored on one player means the other player has no record.** The `trade_state` field lives on the initiating player's Trading aspect data. The other player has no `trade_state` field, no pending trade indicator, and no way to query whether a trade is active with them. If the initiating player disconnects, the trade_state persists on their aspect record with no cleanup mechanism. The other player cannot cancel a trade they did not initiate. This asymmetry creates confusion: Player B receives a trade request event, but if they disconnect and reconnect, there is no way to resume or even see the pending trade -- the state is entirely on Player A.

**Merchant gold depletion means sell commands can fail unexpectedly.** Merchants have finite gold (their own gold entity with a stack_count). A merchant NPC with 1000 gold who buys items from players will eventually run out. When a player tries to `sell` an item worth 50 gold to a merchant with 30 gold remaining, the command fails with "merchant cannot afford this." The player has no way to know the merchant's gold balance before attempting the sale. Worse, in a busy settlement with 5 players selling to the same merchant, the merchant's gold depletes rapidly and unpredictably. This is realistic but frustrating -- players expect merchants to always buy their junk.

**NPC merchant inventory creates item entities that persist in DynamoDB.** Each item a merchant sells is an entity with an Inventory aspect -- 2 DynamoDB records per item. A merchant with 10 items for sale has 20 records. When a player buys an item, those records are updated (location changes) but never deleted. When the merchant restocks (if implemented), new entities are created. Over time, the merchant accumulates a history of every item ever created for sale. There is no garbage collection. If merchant restocking runs on a tick (every 30 seconds), and creates 1-2 items per restock, that is 2-4 DynamoDB writes per tick per merchant, adding up across the world.

**Faction price modifiers require loading the Faction aspect per transaction.** Every `buy` and `sell` command that involves a faction-affiliated merchant must load the player's Faction aspect (1 DynamoDB read), look up the faction reputation, and compute the price modifier. This adds 1 read to every trade operation. With 50 players buying and selling across 20 merchants, that is 50 additional reads per batch of transactions. On a 1 RCU table, this is noticeable but not catastrophic. The real cost is latency: each buy/sell command now requires reading Trading aspect, Inventory aspect (for gold), Inventory aspect (for the item), Faction aspect (for price modifier), and the merchant's NPC aspect -- 5 aspect reads before the command can execute.

**This is a CRITICAL ENABLER for Crafting, Dialogue, and Faction.** The Crafting design (02-crafting.md) notes "no currency or exchange mechanism" as a critical gap. The Dialogue design (09-dialogue-trees.md) defines `show_trade_inventory` and `show_player_sellable_items` actions but has no buy/sell implementation. The Faction design (07-faction-reputation.md) references "better trade prices" at friendly standing but has no price system. Trading fills all three gaps simultaneously. Without it, merchants are props, crafted items have no market, and faction reputation bonuses are decorative.

**The 50% buy-back ratio is a gold sink but may be too aggressive.** Buying a sword for 100 gold and immediately selling it back yields 50 gold -- a 50% loss. This is standard RPG design (prevents infinite gold exploits), but with limited merchant gold pools, the economy can deflate rapidly. If players are generating gold primarily through combat loot and spending it on merchant items, the 50% haircut on resale combined with merchant gold depletion means gold permanently leaves the economy. There is no gold generation mechanism for merchants (they do not earn gold from thin air), so the total gold supply in the world is fixed at whatever was created during world generation plus combat drops.

## Overview

The Trading aspect adds currency (gold), NPC merchant buy/sell transactions, and player-to-player item trading to the game. Gold is represented as a special item entity with a `stack_count` property, avoiding the need for thousands of individual coin entities. Merchants have inventories of items for sale with prices defined in a registry, and will buy items matching their `buy_tags` list at 50% of the sell price. Player-to-player trade uses a stateful three-step process: initiate, offer items, accept or decline. Faction reputation modifies merchant prices.

## Design Principles

**Gold is an item.** Currency is not a special field on the player -- it is an entity with an Inventory aspect, `tags: ["currency"]`, and a `stack_count` property. This means gold follows all existing item rules: it can be dropped, picked up, traded, and stored. No special currency infrastructure needed.

**Prices are data, not code.** Item prices live in a PRICE_REGISTRY dict, keyed by item name or tag. Adding a price for a new item means adding a data entry. Merchants reference this registry rather than hardcoding prices on individual items.

**Trade is explicit and consensual.** Player-to-player trade requires both parties to act: one initiates, both offer items, and one accepts. There is no way to take items from another player without their participation. The three-step process gives both players a chance to review and cancel.

**Each aspect owns its data.** Trading stores `trade_state` on the player's aspect record. Gold is an Inventory aspect item. Merchant configuration (trade_inventory, buy_tags) lives on the NPC aspect. Prices live in a module-level registry.

## Aspect Data

Stored in **LOCATION_TABLE** (shared aspect table, keyed by entity UUID):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| uuid | str | - | Entity UUID (primary key) |
| trade_state | dict | {} | Active player-to-player trade (empty = no active trade) |
| total_earned | int | 0 | Lifetime gold earned (for stats/achievements) |
| total_spent | int | 0 | Lifetime gold spent (for stats/achievements) |

### Trade State Structure

When a player initiates a trade, `trade_state` is populated:

```python
{
    "partner_uuid": "other-player-uuid",
    "partner_name": "OtherPlayer",
    "my_offers": ["item-uuid-1", "item-uuid-2"],
    "my_gold_offer": 50,
    "partner_offers": ["item-uuid-3"],
    "partner_gold_offer": 0,
    "status": "pending",  # pending | offering | ready
    "initiated_at": 1700000000
}
```

### Gold Entity Structure

Gold is a standard item entity with special properties in its Inventory aspect:

```python
{
    "uuid": "gold-entity-uuid",
    "is_item": True,
    "tags": ["currency"],
    "stack_count": 500,
    "weight": 0,
    "description": "A pouch of gold coins.",
}
```

### Price Registry

```python
PRICE_REGISTRY = {
    # Weapons
    "a wooden club": {"buy": 10, "sell": 5},
    "iron sword": {"buy": 50, "sell": 25},
    "steel longsword": {"buy": 150, "sell": 75},

    # Armor
    "leather armor": {"buy": 80, "sell": 40},
    "iron shield": {"buy": 60, "sell": 30},

    # Consumables
    "healing herb": {"buy": 15, "sell": 7},
    "torch": {"buy": 5, "sell": 2},
    "antidote": {"buy": 25, "sell": 12},

    # Materials (merchants buy these from players)
    "wood": {"buy": None, "sell": 3},   # Merchants don't sell raw wood
    "stone": {"buy": None, "sell": 3},
    "leather": {"buy": None, "sell": 8},
    "metal": {"buy": None, "sell": 12},
    "herb": {"buy": None, "sell": 5},

    # Tag-based fallback prices (for items not explicitly listed)
    "_tag_defaults": {
        "weapon": {"buy": 30, "sell": 15},
        "armor": {"buy": 50, "sell": 25},
        "consumable": {"buy": 10, "sell": 5},
        "material": {"buy": None, "sell": 5},
    },
}
```

### Merchant NPC Data Extensions

Added to the NPC aspect's data:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| trade_inventory | list | [] | List of item names this merchant sells |
| buy_tags | list | [] | Item tags this merchant will buy (e.g., ["weapon", "material"]) |
| merchant_gold | str | "" | UUID of merchant's gold entity |
| faction | str | "" | Faction affiliation (affects pricing) |

## Commands

### `balance`

```python
@player_command
def balance(self) -> dict:
    """Show current gold balance."""
```

**Validation:** None -- always succeeds.

**Behavior:**
1. Search entity contents for an item with `"currency"` tag
2. If found, read its `stack_count`
3. If not found, player has 0 gold

```python
@player_command
def balance(self) -> dict:
    """Show current gold balance."""
    gold_amount = self._get_gold_count()
    return {
        "type": "balance",
        "gold": gold_amount,
        "message": f"You have {gold_amount} gold.",
    }

def _get_gold_count(self) -> int:
    """Find the player's gold entity and return stack_count."""
    for item_uuid in self.entity.contents:
        try:
            item_entity = Entity(uuid=item_uuid)
            item_inv = item_entity.aspect("Inventory")
            if "currency" in item_inv.data.get("tags", []):
                return item_inv.data.get("stack_count", 0)
        except (KeyError, ValueError):
            continue
    return 0

def _get_gold_entity(self):
    """Find and return the player's gold entity and its Inventory aspect, or (None, None)."""
    for item_uuid in self.entity.contents:
        try:
            item_entity = Entity(uuid=item_uuid)
            item_inv = item_entity.aspect("Inventory")
            if "currency" in item_inv.data.get("tags", []):
                return item_entity, item_inv
        except (KeyError, ValueError):
            continue
    return None, None
```

**DynamoDB cost:** O(N) reads where N = items in inventory (to find the gold entity). Each item requires 1 entity read + 1 aspect read = 2N reads total.

**Return format:**
```python
{
    "type": "balance",
    "gold": 500,
    "message": "You have 500 gold."
}
```

### `buy <item_name> from <npc_uuid>`

```python
@player_command
def buy(self, item_name: str, npc_uuid: str) -> dict:
    """Buy an item from a merchant NPC."""
```

**Validation:**
1. NPC must exist and be at the same location
2. NPC must have `"merchant"` behavior in NPC aspect
3. NPC must have `item_name` in `trade_inventory`
4. Item must have a price in PRICE_REGISTRY (or tag default)
5. Player must have enough gold

**Behavior:**
```python
@player_command
def buy(self, item_name: str, npc_uuid: str) -> dict:
    """Buy an item from a merchant NPC."""
    # Load and validate merchant
    try:
        merchant_entity = Entity(uuid=npc_uuid)
    except KeyError:
        return {"type": "error", "message": "That merchant doesn't exist."}

    if merchant_entity.location != self.entity.location:
        return {"type": "error", "message": "That merchant isn't here."}

    try:
        merchant_npc = merchant_entity.aspect("NPC")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a merchant."}

    if merchant_npc.data.get("behavior") != "merchant":
        return {"type": "error", "message": "That's not a merchant."}

    # Check merchant has item
    trade_inventory = merchant_npc.data.get("trade_inventory", [])
    if item_name not in trade_inventory:
        return {"type": "error", "message": f"The merchant doesn't sell '{item_name}'."}

    # Look up price
    price = self._get_buy_price(item_name, merchant_npc)
    if price is None:
        return {"type": "error", "message": f"'{item_name}' is not for sale."}

    # Apply faction price modifier
    price = self._apply_faction_modifier(price, merchant_npc, is_buying=True)

    # Check player gold
    gold_entity, gold_inv = self._get_gold_entity()
    player_gold = gold_inv.data.get("stack_count", 0) if gold_inv else 0
    if player_gold < price:
        return {
            "type": "error",
            "message": f"Not enough gold. {item_name} costs {price} gold, you have {player_gold}.",
        }

    # Deduct gold from player
    gold_inv.data["stack_count"] = player_gold - price
    gold_inv._save()

    # Add gold to merchant
    self._add_gold_to_entity(merchant_entity, price)

    # Create item in player inventory
    inv = self.entity.aspect("Inventory")
    registry_entry = PRICE_REGISTRY.get(item_name, {})
    item_result = inv.create_item(
        name=item_name,
        description=registry_entry.get("description", f"A purchased {item_name}."),
        tags=registry_entry.get("tags", []),
        weight=registry_entry.get("weight", 1),
    )

    # Track stats
    self.data["total_spent"] = self.data.get("total_spent", 0) + price
    self._save()

    return {
        "type": "buy_confirm",
        "item_name": item_name,
        "item_uuid": item_result.get("item_uuid", ""),
        "price": price,
        "remaining_gold": player_gold - price,
        "message": f"You buy {item_name} for {price} gold.",
    }
```

**DynamoDB cost:**
- 1 read: merchant entity
- 1 read: merchant NPC aspect
- O(N) reads: find player's gold entity (N = inventory size)
- 1 read: player Faction aspect (for price modifier)
- 1 write: player gold Inventory aspect (deduct gold)
- 1 write: merchant gold Inventory aspect (add gold)
- 2 writes: create item (entity + Inventory aspect)
- 1 write: Trading aspect (stats update)
- Total: ~2N + 3 reads, 5 writes

**Return format:**
```python
{
    "type": "buy_confirm",
    "item_name": "healing herb",
    "item_uuid": "new-item-uuid",
    "price": 15,
    "remaining_gold": 485,
    "message": "You buy healing herb for 15 gold."
}
```

### `sell <item_uuid> to <npc_uuid>`

```python
@player_command
def sell(self, item_uuid: str, npc_uuid: str) -> dict:
    """Sell an item to a merchant NPC."""
```

**Validation:**
1. Item must be in player's inventory
2. NPC must exist and be at the same location
3. NPC must be a merchant
4. Item must have tags matching merchant's `buy_tags`
5. Merchant must have enough gold to pay

**Behavior:**
```python
@player_command
def sell(self, item_uuid: str, npc_uuid: str) -> dict:
    """Sell an item to a merchant NPC."""
    # Validate item is in inventory
    try:
        item_entity = Entity(uuid=item_uuid)
    except KeyError:
        return {"type": "error", "message": "That item doesn't exist."}

    if item_entity.location != self.entity.uuid:
        return {"type": "error", "message": "You don't have that item."}

    try:
        item_inv = item_entity.aspect("Inventory")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a sellable item."}

    # Load and validate merchant
    try:
        merchant_entity = Entity(uuid=npc_uuid)
    except KeyError:
        return {"type": "error", "message": "That merchant doesn't exist."}

    if merchant_entity.location != self.entity.location:
        return {"type": "error", "message": "That merchant isn't here."}

    try:
        merchant_npc = merchant_entity.aspect("NPC")
    except (ValueError, KeyError):
        return {"type": "error", "message": "That's not a merchant."}

    if merchant_npc.data.get("behavior") != "merchant":
        return {"type": "error", "message": "That's not a merchant."}

    # Check merchant will buy this item (tag match)
    buy_tags = merchant_npc.data.get("buy_tags", [])
    item_tags = item_inv.data.get("tags", [])
    if not any(tag in buy_tags for tag in item_tags):
        return {"type": "error", "message": "The merchant isn't interested in that."}

    # Calculate sell price (50% of buy price)
    sell_price = self._get_sell_price(item_entity.name, item_tags)
    if sell_price is None or sell_price <= 0:
        return {"type": "error", "message": "That item has no trade value."}

    # Apply faction modifier
    sell_price = self._apply_faction_modifier(sell_price, merchant_npc, is_buying=False)

    # Check merchant can afford it
    merchant_gold = self._get_entity_gold_count(merchant_entity)
    if merchant_gold < sell_price:
        return {
            "type": "error",
            "message": f"The merchant can't afford that. They only have {merchant_gold} gold.",
        }

    # Transfer gold: merchant -> player
    self._deduct_gold_from_entity(merchant_entity, sell_price)
    self._add_gold_to_self(sell_price)

    # Transfer item: player -> merchant (or destroy it)
    item_entity.location = merchant_entity.uuid

    item_name = item_entity.name

    # Track stats
    self.data["total_earned"] = self.data.get("total_earned", 0) + sell_price
    self._save()

    return {
        "type": "sell_confirm",
        "item_name": item_name,
        "item_uuid": item_uuid,
        "price": sell_price,
        "message": f"You sell {item_name} for {sell_price} gold.",
    }
```

**DynamoDB cost:**
- 1 read: item entity
- 1 read: item Inventory aspect
- 1 read: merchant entity
- 1 read: merchant NPC aspect
- O(M) reads: find merchant gold entity (M = merchant inventory size)
- O(N) reads: find player gold entity (N = player inventory size)
- 1 read: player Faction aspect
- 1 write: merchant gold (deduct)
- 1 write: player gold (add)
- 1 write: item entity (change location to merchant)
- 1 write: Trading aspect (stats)
- Total: ~N + M + 5 reads, 4 writes

**Return format:**
```python
{
    "type": "sell_confirm",
    "item_name": "iron sword",
    "item_uuid": "item-uuid",
    "price": 25,
    "message": "You sell iron sword for 25 gold."
}
```

### `trade <player_uuid>`

```python
@player_command
def trade(self, player_uuid: str) -> dict:
    """Initiate a trade with another player at the same location."""
```

**Validation:**
1. Target must exist and be at the same location
2. Target must be a connected player (has `connection_id`)
3. Neither player can have an active trade already
4. Cannot trade with self

**Behavior:**
```python
@player_command
def trade(self, player_uuid: str) -> dict:
    """Initiate a trade with another player at the same location."""
    if player_uuid == self.entity.uuid:
        return {"type": "error", "message": "You can't trade with yourself."}

    # Check for existing trade
    if self.data.get("trade_state", {}):
        return {"type": "error", "message": "You already have an active trade. Accept, decline, or wait."}

    # Load target
    try:
        target_entity = Entity(uuid=player_uuid)
    except KeyError:
        return {"type": "error", "message": "That player doesn't exist."}

    if target_entity.location != self.entity.location:
        return {"type": "error", "message": "That player isn't here."}

    if not target_entity.connection_id:
        return {"type": "error", "message": "That player isn't online."}

    # Check target doesn't have active trade
    try:
        target_trading = target_entity.aspect("Trading")
        if target_trading.data.get("trade_state", {}):
            return {"type": "error", "message": "That player is already trading with someone."}
    except (ValueError, KeyError):
        pass

    # Create trade state on initiator
    import time
    self.data["trade_state"] = {
        "partner_uuid": player_uuid,
        "partner_name": target_entity.name,
        "my_offers": [],
        "my_gold_offer": 0,
        "partner_offers": [],
        "partner_gold_offer": 0,
        "status": "pending",
        "initiated_at": int(time.time()),
    }
    self._save()

    # Notify the target player
    target_entity.push_event({
        "type": "trade_request",
        "from_uuid": self.entity.uuid,
        "from_name": self.entity.name,
        "message": f"{self.entity.name} wants to trade with you. Use 'trade {self.entity.uuid}' to accept.",
    })

    return {
        "type": "trade_initiated",
        "partner": target_entity.name,
        "partner_uuid": player_uuid,
        "message": f"Trade request sent to {target_entity.name}. Waiting for response.",
    }
```

**DynamoDB cost:** 1 read (target entity) + 1 read (target Trading aspect) + 1 write (self Trading aspect) = 2 reads, 1 write.

**Return format:**
```python
{
    "type": "trade_initiated",
    "partner": "OtherPlayer",
    "partner_uuid": "other-uuid",
    "message": "Trade request sent to OtherPlayer. Waiting for response."
}
```

### `offer <item_uuid>`

```python
@player_command
def offer(self, item_uuid: str, gold: int = 0) -> dict:
    """Offer an item or gold in an active trade."""
```

**Validation:**
1. Must have an active trade (trade_state not empty)
2. If item_uuid provided: item must be in player's inventory
3. If gold provided: player must have enough gold
4. Cannot offer same item twice

**Behavior:**
```python
@player_command
def offer(self, item_uuid: str = "", gold: int = 0) -> dict:
    """Offer an item or gold in an active trade."""
    trade = self.data.get("trade_state", {})
    if not trade:
        return {"type": "error", "message": "You don't have an active trade."}

    partner_uuid = trade["partner_uuid"]

    if item_uuid:
        # Validate item is in inventory
        try:
            item_entity = Entity(uuid=item_uuid)
        except KeyError:
            return {"type": "error", "message": "That item doesn't exist."}

        if item_entity.location != self.entity.uuid:
            return {"type": "error", "message": "You don't have that item."}

        if item_uuid in trade.get("my_offers", []):
            return {"type": "error", "message": "You already offered that item."}

        trade.setdefault("my_offers", []).append(item_uuid)
        item_name = item_entity.name
    else:
        item_name = None

    if gold > 0:
        player_gold = self._get_gold_count()
        if gold > player_gold:
            return {"type": "error", "message": f"You only have {player_gold} gold."}
        trade["my_gold_offer"] = trade.get("my_gold_offer", 0) + gold

    self.data["trade_state"] = trade
    self._save()

    # Notify partner
    try:
        partner = Entity(uuid=partner_uuid)
        offer_msg = ""
        if item_name:
            offer_msg += f"{self.entity.name} offers {item_name}. "
        if gold > 0:
            offer_msg += f"{self.entity.name} offers {gold} gold. "

        partner.push_event({
            "type": "trade_offer",
            "from_uuid": self.entity.uuid,
            "from_name": self.entity.name,
            "item_uuid": item_uuid,
            "item_name": item_name,
            "gold": gold,
            "message": offer_msg.strip(),
        })
    except KeyError:
        pass

    return {
        "type": "offer_confirm",
        "item_uuid": item_uuid,
        "item_name": item_name,
        "gold": gold,
        "message": f"Offered{' ' + item_name if item_name else ''}{' and ' + str(gold) + ' gold' if gold > 0 else ''}.",
    }
```

**Return format:**
```python
{
    "type": "offer_confirm",
    "item_uuid": "item-uuid",
    "item_name": "iron sword",
    "gold": 0,
    "message": "Offered iron sword."
}
```

### `accept`

```python
@player_command
def accept(self) -> dict:
    """Accept the current trade, transferring all offered items and gold."""
```

**Validation:**
1. Must have an active trade
2. Both players must still be at the same location
3. All offered items must still be in the correct inventories
4. Both players must have sufficient gold for their gold offers

**Behavior:**
```python
@player_command
def accept(self) -> dict:
    """Accept the current trade, transferring all offered items and gold."""
    trade = self.data.get("trade_state", {})
    if not trade:
        return {"type": "error", "message": "You don't have an active trade."}

    partner_uuid = trade["partner_uuid"]

    try:
        partner_entity = Entity(uuid=partner_uuid)
    except KeyError:
        self.data["trade_state"] = {}
        self._save()
        return {"type": "error", "message": "Trade partner no longer exists."}

    if partner_entity.location != self.entity.location:
        self.data["trade_state"] = {}
        self._save()
        return {"type": "error", "message": "Trade partner is no longer here. Trade cancelled."}

    # Re-validate all offered items still exist in correct inventories
    my_offers = trade.get("my_offers", [])
    partner_offers = trade.get("partner_offers", [])

    for iuuid in my_offers:
        try:
            ie = Entity(uuid=iuuid)
            if ie.location != self.entity.uuid:
                self.data["trade_state"] = {}
                self._save()
                return {"type": "error", "message": "One of your offered items is no longer available. Trade cancelled."}
        except KeyError:
            self.data["trade_state"] = {}
            self._save()
            return {"type": "error", "message": "One of your offered items no longer exists. Trade cancelled."}

    for iuuid in partner_offers:
        try:
            ie = Entity(uuid=iuuid)
            if ie.location != partner_uuid:
                self.data["trade_state"] = {}
                self._save()
                return {"type": "error", "message": "One of the partner's offered items is no longer available. Trade cancelled."}
        except KeyError:
            self.data["trade_state"] = {}
            self._save()
            return {"type": "error", "message": "One of the partner's offered items no longer exists. Trade cancelled."}

    # Transfer items: my_offers -> partner, partner_offers -> me
    for iuuid in my_offers:
        item = Entity(uuid=iuuid)
        item.location = partner_uuid

    for iuuid in partner_offers:
        item = Entity(uuid=iuuid)
        item.location = self.entity.uuid

    # Transfer gold
    my_gold_offer = trade.get("my_gold_offer", 0)
    partner_gold_offer = trade.get("partner_gold_offer", 0)

    if my_gold_offer > 0:
        self._deduct_gold(my_gold_offer)
        self._add_gold_to_entity(partner_entity, my_gold_offer)

    if partner_gold_offer > 0:
        self._deduct_gold_from_entity(partner_entity, partner_gold_offer)
        self._add_gold_to_self(partner_gold_offer)

    # Clear trade state
    self.data["trade_state"] = {}
    self._save()

    # Clear partner trade state if they have one
    try:
        partner_trading = partner_entity.aspect("Trading")
        partner_trading.data["trade_state"] = {}
        partner_trading._save()
    except (ValueError, KeyError):
        pass

    # Notify partner
    partner_entity.push_event({
        "type": "trade_complete",
        "partner_name": self.entity.name,
        "received_items": len(my_offers),
        "received_gold": my_gold_offer,
        "message": f"Trade with {self.entity.name} complete.",
    })

    return {
        "type": "trade_complete",
        "partner_name": trade.get("partner_name", ""),
        "received_items": len(partner_offers),
        "received_gold": partner_gold_offer,
        "given_items": len(my_offers),
        "given_gold": my_gold_offer,
        "message": f"Trade with {trade.get('partner_name', '')} complete.",
    }
```

**DynamoDB cost:** O(N + M) reads to validate items + O(N + M) writes to transfer items + up to 4 reads/writes for gold transfer + 2 writes for trade state cleanup. For a trade with 3 items each side, that is roughly 12 reads + 10 writes.

**Return format:**
```python
{
    "type": "trade_complete",
    "partner_name": "OtherPlayer",
    "received_items": 2,
    "received_gold": 50,
    "given_items": 1,
    "given_gold": 0,
    "message": "Trade with OtherPlayer complete."
}
```

### `decline`

```python
@player_command
def decline(self) -> dict:
    """Decline or cancel the current trade."""
```

**Behavior:**
```python
@player_command
def decline(self) -> dict:
    """Decline or cancel the current trade."""
    trade = self.data.get("trade_state", {})
    if not trade:
        return {"type": "error", "message": "You don't have an active trade."}

    partner_uuid = trade.get("partner_uuid", "")
    partner_name = trade.get("partner_name", "someone")

    # Notify partner
    try:
        partner_entity = Entity(uuid=partner_uuid)
        partner_entity.push_event({
            "type": "trade_declined",
            "from_name": self.entity.name,
            "message": f"{self.entity.name} declined the trade.",
        })
        # Clear partner's trade state too
        partner_trading = partner_entity.aspect("Trading")
        partner_trading.data["trade_state"] = {}
        partner_trading._save()
    except (KeyError, ValueError):
        pass

    # Clear own trade state
    self.data["trade_state"] = {}
    self._save()

    return {
        "type": "trade_declined",
        "message": f"Trade with {partner_name} cancelled.",
    }
```

**Return format:**
```python
{
    "type": "trade_declined",
    "message": "Trade with OtherPlayer cancelled."
}
```

## Cross-Aspect Interactions

### Trading + Inventory (gold management)

Gold is an Inventory item. The Trading aspect reads and writes gold entities through the Inventory aspect:

```python
def _add_gold_to_self(self, amount: int):
    """Add gold to this entity's gold stack, creating one if needed."""
    gold_entity, gold_inv = self._get_gold_entity()
    if gold_inv:
        gold_inv.data["stack_count"] = gold_inv.data.get("stack_count", 0) + amount
        gold_inv._save()
    else:
        # Create a new gold entity in player's inventory
        inv = self.entity.aspect("Inventory")
        inv.create_item(
            name="gold coins",
            description="A pouch of gold coins.",
            tags=["currency"],
            stack_count=amount,
            weight=0,
            is_item=True,
        )

def _deduct_gold(self, amount: int):
    """Deduct gold from this entity's gold stack."""
    gold_entity, gold_inv = self._get_gold_entity()
    if not gold_inv:
        raise ValueError("No gold to deduct")
    current = gold_inv.data.get("stack_count", 0)
    if current < amount:
        raise ValueError(f"Insufficient gold: have {current}, need {amount}")
    gold_inv.data["stack_count"] = current - amount
    gold_inv._save()

def _add_gold_to_entity(self, target_entity: "Entity", amount: int):
    """Add gold to another entity's gold stack."""
    for item_uuid in target_entity.contents:
        try:
            item_entity = Entity(uuid=item_uuid)
            item_inv = item_entity.aspect("Inventory")
            if "currency" in item_inv.data.get("tags", []):
                item_inv.data["stack_count"] = item_inv.data.get("stack_count", 0) + amount
                item_inv._save()
                return
        except (KeyError, ValueError):
            continue
    # No gold entity found -- create one
    from .inventory import Inventory
    gold = Entity()
    gold.data["name"] = "gold coins"
    gold.data["location"] = target_entity.uuid
    gold.data["aspects"] = ["Inventory"]
    gold.data["primary_aspect"] = "Inventory"
    gold._save()
    gold_inv = Inventory()
    gold_inv.data["uuid"] = gold.uuid
    gold_inv.data["is_item"] = True
    gold_inv.data["tags"] = ["currency"]
    gold_inv.data["stack_count"] = amount
    gold_inv.data["weight"] = 0
    gold_inv.data["description"] = "A pouch of gold coins."
    gold_inv._save()
```

### Trading + NPC (merchant behavior)

Merchants are NPCs with trade-specific data. The Trading aspect reads merchant configuration from the NPC aspect:

```python
def _get_buy_price(self, item_name: str, merchant_npc) -> int:
    """Look up the buy price for an item from the PRICE_REGISTRY."""
    entry = PRICE_REGISTRY.get(item_name)
    if entry and entry.get("buy") is not None:
        return entry["buy"]

    # Fallback: check tag defaults
    trade_inv = merchant_npc.data.get("trade_inventory", [])
    defaults = PRICE_REGISTRY.get("_tag_defaults", {})
    for tag, prices in defaults.items():
        if prices.get("buy") is not None:
            return prices["buy"]
    return None

def _get_sell_price(self, item_name: str, item_tags: list) -> int:
    """Look up the sell price (50% of buy, or explicit sell price)."""
    entry = PRICE_REGISTRY.get(item_name)
    if entry and entry.get("sell") is not None:
        return entry["sell"]

    # Fallback: tag-based pricing
    defaults = PRICE_REGISTRY.get("_tag_defaults", {})
    for tag in item_tags:
        if tag in defaults and defaults[tag].get("sell") is not None:
            return defaults[tag]["sell"]
    return None
```

### Trading + Faction (price modifiers)

Faction reputation modifies merchant prices. Friendly players get discounts, hostile players pay more:

```python
FACTION_PRICE_TIERS = {
    # (min_rep, max_rep): multiplier
    (-100, -50): 1.30,   # Hostile: +30% buy, -30% sell
    (-49, -10):  1.15,   # Unfriendly: +15% buy, -15% sell
    (-9, 9):     1.00,   # Neutral: base price
    (10, 49):    0.90,   # Friendly: -10% buy, +10% sell
    (50, 100):   0.80,   # Honored: -20% buy, +20% sell
}

def _apply_faction_modifier(self, base_price: int, merchant_npc, is_buying: bool) -> int:
    """Apply faction reputation modifier to a price."""
    faction_id = merchant_npc.data.get("faction", "")
    if not faction_id:
        return base_price

    try:
        faction_aspect = self.entity.aspect("Faction")
        rep = faction_aspect.data.get("reputation", {}).get(faction_id, 0)
    except (ValueError, KeyError):
        return base_price

    multiplier = 1.0
    for (min_rep, max_rep), tier_mult in FACTION_PRICE_TIERS.items():
        if min_rep <= rep <= max_rep:
            multiplier = tier_mult
            break

    if is_buying:
        # Buying: lower multiplier = cheaper for the player
        return max(1, int(base_price * multiplier))
    else:
        # Selling: invert the modifier -- friendly means better sell price
        inverse = 2.0 - multiplier  # 0.80 -> 1.20, 1.30 -> 0.70
        return max(1, int(base_price * inverse))
```

### Trading + Crafting (market for crafted goods)

Crafted items automatically have trade value based on their tags. A player who crafts a "wooden club" (tags: ["weapon", "melee", "wood"]) can sell it to any merchant with `"weapon"` in their `buy_tags`. The PRICE_REGISTRY entry for "a wooden club" sets buy: 10, sell: 5. This closes the loop that Crafting left open -- crafted items now have economic value.

```python
# A merchant dialogue tree can reference Trading commands:
# "browse" node action triggers _show_trade_inventory which reads
# merchant NPC's trade_inventory list and presents items with prices.

# In Crafting.craft(), after creating the item:
# The item already has tags from the recipe output definition.
# No Trading-specific changes needed -- sell price is looked up by name/tags.
```

### Trading + Combat (loot gold drops)

When a combat entity dies and drops loot, gold entities among the loot maintain their stack_count:

```python
# No changes to Combat._on_death() needed.
# Gold entities are items. When dropped (location set to room UUID),
# another player can pick them up with Inventory.take().
# The stack_count property persists on the Inventory aspect.
```

### Trading + Dialogue (merchant trade flow)

The Dialogue system's `show_trade_inventory` action can now call Trading commands:

```python
# In NPC._execute_action():
if action["type"] == "show_trade_inventory":
    trade_inv = self.data.get("trade_inventory", [])
    items_with_prices = []
    for item_name in trade_inv:
        entry = PRICE_REGISTRY.get(item_name, {})
        price = entry.get("buy")
        if price is not None:
            items_with_prices.append({
                "name": item_name,
                "price": price,
                "description": entry.get("description", ""),
            })
    player.push_event({
        "type": "trade_inventory",
        "npc_name": self.entity.name,
        "npc_uuid": self.entity.uuid,
        "items": items_with_prices,
        "message": f"Use 'buy <item_name> from {self.entity.uuid}' to purchase.",
    })
```

## Event Flow

### Buy From Merchant

```
Player sends: {"command": "buy", "data": {"item_name": "healing herb", "npc_uuid": "merchant-uuid"}}
  -> Entity.receive_command(command="buy", ...)
    -> Trading.buy(item_name="healing herb", npc_uuid="merchant-uuid")
      -> Load merchant entity (1 read)
      -> Validate merchant is at same location
      -> Load merchant NPC aspect (1 read) -- check behavior, trade_inventory
      -> Look up price in PRICE_REGISTRY
      -> Load player Faction aspect (1 read) -- compute price modifier
      -> Find player gold entity -- scan contents (O(N) reads)
      -> Deduct gold from player (1 write to Inventory aspect)
      -> Add gold to merchant (O(M) reads + 1 write)
      -> Create item in player inventory (2 writes: entity + aspect)
      -> Save Trading aspect (1 write)
      -> push_event(buy_confirm to player)
```

### Sell To Merchant

```
Player sends: {"command": "sell", "data": {"item_uuid": "sword-uuid", "npc_uuid": "merchant-uuid"}}
  -> Trading.sell(item_uuid="sword-uuid", npc_uuid="merchant-uuid")
    -> Load item entity + Inventory aspect (2 reads)
    -> Load merchant entity + NPC aspect (2 reads)
    -> Check buy_tags match
    -> Look up sell price (50% of buy price)
    -> Load Faction aspect for price modifier (1 read)
    -> Check merchant gold (O(M) reads)
    -> Deduct gold from merchant (1 write)
    -> Add gold to player (O(N) reads + 1 write)
    -> Move item to merchant (1 write to entity table)
    -> Save Trading aspect (1 write)
    -> push_event(sell_confirm)
```

### Player-to-Player Trade

```
Player A sends: {"command": "trade", "data": {"player_uuid": "player-b-uuid"}}
  -> Trading.trade(player_uuid="player-b-uuid")
    -> Validate Player B is at same location, connected, not in trade
    -> Create trade_state on Player A's Trading aspect
    -> push_event(trade_request) to Player B

Player A sends: {"command": "offer", "data": {"item_uuid": "sword-uuid"}}
  -> Trading.offer(item_uuid="sword-uuid")
    -> Validate item in inventory, trade active
    -> Add item UUID to trade_state.my_offers
    -> push_event(trade_offer) to Player B

Player B sends: {"command": "offer", "data": {"item_uuid": "shield-uuid"}}
  -> Trading.offer(item_uuid="shield-uuid")
    -> (If B accepted the trade request, B also has trade_state)
    -> Add item to trade_state.my_offers
    -> push_event(trade_offer) to Player A

Player A sends: {"command": "accept"}
  -> Trading.accept()
    -> Re-validate all offered items still in correct inventories
    -> Transfer items: A's offers -> B's inventory, B's offers -> A's inventory
    -> Transfer gold if any
    -> Clear trade_state on both players
    -> push_event(trade_complete) to both
```

## NPC Integration

### Creating merchant NPCs

```python
# During world generation:
merchant_entity = Entity()
merchant_entity.data["name"] = "Grimbold the Trader"
merchant_entity.data["location"] = settlement_room_uuid
merchant_entity.data["aspects"] = ["NPC", "Inventory", "Trading"]
merchant_entity.data["primary_aspect"] = "NPC"
merchant_entity._save()

# Set NPC behavior
npc = merchant_entity.aspect("NPC")
npc.data["behavior"] = "merchant"
npc.data["is_npc"] = True
npc.data["trade_inventory"] = ["healing herb", "torch", "antidote", "iron sword", "leather armor"]
npc.data["buy_tags"] = ["weapon", "armor", "material", "herb"]
npc.data["faction"] = "settlement_folk"
npc._save()

# Give the merchant starting gold
from aspects.inventory import Inventory
gold = Entity()
gold.data["name"] = "gold coins"
gold.data["location"] = merchant_entity.uuid
gold.data["aspects"] = ["Inventory"]
gold.data["primary_aspect"] = "Inventory"
gold._save()

gold_inv = Inventory()
gold_inv.data["uuid"] = gold.uuid
gold_inv.data["is_item"] = True
gold_inv.data["tags"] = ["currency"]
gold_inv.data["stack_count"] = 1000
gold_inv.data["weight"] = 0
gold_inv.data["description"] = "A heavy pouch of gold coins."
gold_inv._save()
```

### Merchant restocking

Merchants do not restock automatically in the initial implementation. Their `trade_inventory` list defines what they can sell -- items are created on purchase, not pre-created. The list acts as a catalog, not a physical inventory. This avoids the entity bloat problem of pre-creating item entities.

If physical merchant inventories are desired later, restocking can run on the NPC tick:

```python
# Future: in NPC.tick() for merchants
def _merchant_restock(self):
    """Periodically refresh the merchant's item stock."""
    # Only restock if below threshold
    current_items = [uuid for uuid in self.entity.contents]
    if len(current_items) >= self.data.get("max_stock", 10):
        return
    # Create items from trade_inventory catalog
    # This adds 2 writes per restocked item
```

### NPC merchants and dialogue

Merchants work with the Dialogue system (09-dialogue-trees.md). A player can `talk <merchant>` to browse wares via dialogue, then use `buy` and `sell` commands for actual transactions. The dialogue tree presents information; Trading commands execute transactions.

## AI Agent Considerations

### Economic decision-making

AI agents receive structured data from all Trading commands, making economic decisions straightforward:

1. **Inventory valuation:** Use `inventory` to list items, then check each against PRICE_REGISTRY (available via `examine` which shows item tags) to estimate total value
2. **Buy decisions:** Compare item utility (does it help with current goals?) against price and current gold
3. **Sell decisions:** Sell items no longer needed (replaced equipment, excess materials) to fund purchases
4. **Merchant discovery:** Track which merchants exist at which locations and what they buy/sell

### Trade negotiation

AI agents can participate in player-to-player trades using the same three-step process:

```
1. Receive trade_request event -> evaluate partner and potential gains
2. If interested: offer items that are low-value to self, high-value to partner
3. Review partner's offers -> accept if favorable, decline if not
```

The structured `trade_offer` events provide item UUIDs that the agent can `examine` to assess value before accepting.

### Gold management

An AI agent's economic loop:
1. Check `balance` to know current gold
2. Identify items needed for quests or combat preparation
3. Navigate to merchants that sell those items
4. `buy` needed items
5. `sell` excess loot and crafted goods to replenish gold
6. Track gold income/spending to avoid going broke

### Faction-aware pricing

An AI agent with access to `reputation` data can optimize merchant choice:
- Buy from merchants of factions where standing is highest (lowest prices)
- Sell to merchants of factions where standing is highest (highest prices)
- Avoid hostile faction merchants entirely (30% price premium)

## Implementation Plan

### Files to create

| File | Purpose |
|------|---------|
| `backend/aspects/trading.py` | Trading aspect class with PRICE_REGISTRY |
| `backend/aspects/tests/test_trading.py` | Unit tests |

### Files to modify

| File | Change |
|------|--------|
| `backend/serverless.yml` | Add `trading` Lambda with SNS filter for `Trading` aspect |
| `backend/aspects/npc.py` | Add `trade_inventory`, `buy_tags`, `merchant_gold` fields to merchant NPCs |
| `backend/aspects/inventory.py` | Ensure `create_item` supports `stack_count` and `tags` properties |

### Implementation order

1. Define PRICE_REGISTRY with prices for existing crafting outputs and basic merchant goods
2. Create `trading.py` with Trading aspect class and gold management helpers
3. Implement `balance` command (simplest, validates gold entity scanning)
4. Implement `buy` command with merchant validation and price lookup
5. Implement `sell` command with tag-based matching and merchant gold checking
6. Implement player-to-player trade state machine (`trade`, `offer`, `accept`, `decline`)
7. Add faction price modifier integration
8. Modify NPC data model for merchant configuration
9. Add Lambda + SNS filter to serverless.yml
10. Write tests (buy, sell, balance, trade lifecycle, faction pricing, insufficient gold, merchant depletion)

## Open Questions

1. **Should merchants have infinite gold?** Finite gold is realistic but creates player frustration when merchants run dry. Options: finite with high cap (10,000 gold), infinite (simple but unrealistic), or regenerating (merchant gains N gold per tick). Start with finite at 1000 gold, monitor whether it causes problems.

2. **Gold creation: where does new gold enter the economy?** Currently, gold exists only if created during worldgen or dropped by combat enemies. If gold leaves the economy faster than it enters (merchant buy/sell spreads destroy gold), the economy deflates. Consider: combat loot drops gold entities, quest rewards include gold, terrain entities can be "gold veins" that yield gold when gathered.

3. **Should the PRICE_REGISTRY be in DynamoDB?** Module-level dict means price changes require code deployment. A DynamoDB table allows runtime price adjustments (admin commands, supply/demand simulation). Start with dict, migrate when balancing demands it.

4. **Trade timeout.** How long should a trade_state persist before auto-cancelling? Currently trades live forever on the initiator's aspect. A 5-minute timeout via `Call.after(seconds=300)` would clean up abandoned trades, but adds Step Functions cost per trade initiation.

5. **Player-to-player trade: should both players see the same trade state?** Currently only the initiator stores trade_state. The partner relies on push_events for information. Storing trade_state on both players doubles the writes but provides symmetry and allows either player to view the trade status. The asymmetry is confusing but cheaper.

6. **Should items have dynamic prices based on supply and demand?** A simple model: track how many of each item merchants have sold/bought in the last N hours, adjust prices accordingly. Adds interesting economics but requires a time-series data store or at least a running counter per item per merchant. Defer until the base economy is stable.

7. **Merchant specialization.** Should different merchant types have different price multipliers? A weapon merchant could buy weapons at 60% instead of 50%, creating incentives to find the right merchant. Adds depth but complicates the PRICE_REGISTRY. Can be implemented later by adding a `specialization_bonus` field to NPC data.
