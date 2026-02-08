"""Suggestion aspect for community feature requests.

Allows players and agents to suggest new features, list existing suggestions,
and vote on ideas. The most popular suggestions guide world development.

Shared fields (name) live on Entity, not on this aspect.
Access them via self.entity.*.
"""

import logging
import time

from .decorators import admin_only, player_command
from .handler import lambdaHandler
from .thing import Aspect, Entity

logger = logging.getLogger(__name__)


class Suggestion(Aspect):
    """Aspect handling feature suggestions and voting.

    Uses its own dedicated SUGGESTION_TABLE — suggestion records are not
    entity aspect records (they are standalone documents with their own UUIDs).
    The Suggestion aspect itself has no persistent per-entity data.
    """

    _tableName = "LOCATION_TABLE"  # Aspect record table (minimal)

    @player_command
    def suggest(self, text: str) -> dict:
        """Submit a new feature suggestion.

        Args:
            text: The suggestion text describing the feature idea.

        Returns:
            dict with suggestion confirmation.
        """
        if not text or not text.strip():
            return {"type": "error", "message": "Suggest what? Please describe your idea."}

        author_name = self.entity.name if self.entity else self.uuid[:8]

        # Create the suggestion as a new record in the suggestion table
        from uuid import uuid4

        from .aws_client import get_dynamodb_table

        suggestion_id = str(uuid4())
        table = get_dynamodb_table("SUGGESTION_TABLE")
        table.put_item(
            Item={
                "uuid": suggestion_id,
                "text": text.strip(),
                "author": author_name,
                "author_uuid": self.entity.uuid if self.entity else self.uuid,
                "status": "pending",
                "votes": 0,
                "voters": [],
                "created_at": int(time.time()),
            }
        )

        return {
            "type": "suggest_confirm",
            "message": f"Suggestion submitted: {text.strip()[:80]}",
            "suggestion_uuid": suggestion_id,
        }

    @player_command
    def suggestions(self, status: str = "pending") -> dict:
        """List current suggestions, sorted by votes.

        Args:
            status: Filter by status (pending, approved, rejected). Default: pending.

        Returns:
            dict with list of suggestions.
        """
        from .aws_client import get_dynamodb_table

        table = get_dynamodb_table("SUGGESTION_TABLE")
        response = table.scan(
            FilterExpression="attribute_exists(#s) AND #s = :status",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":status": status},
        )

        items = response.get("Items", [])
        # Sort by votes descending
        items.sort(key=lambda x: int(x.get("votes", 0)), reverse=True)
        # Limit to top 20
        items = items[:20]

        suggestions = [
            {
                "uuid": item["uuid"],
                "text": item["text"],
                "author": item.get("author", "unknown"),
                "votes": int(item.get("votes", 0)),
                "created_at": int(item.get("created_at", 0)),
            }
            for item in items
        ]

        return {
            "type": "suggestions",
            "status": status,
            "suggestions": suggestions,
            "count": len(suggestions),
        }

    @player_command
    def vote(self, suggestion_uuid: str) -> dict:
        """Upvote a suggestion. Each entity can only vote once per suggestion.

        Args:
            suggestion_uuid: UUID of the suggestion to vote for.

        Returns:
            dict with vote confirmation.
        """
        if not suggestion_uuid:
            return {"type": "error", "message": "Vote for what? Provide a suggestion UUID."}

        from .aws_client import get_dynamodb_table

        table = get_dynamodb_table("SUGGESTION_TABLE")

        try:
            response = table.get_item(Key={"uuid": suggestion_uuid})
        except Exception as e:
            return {"type": "error", "message": f"Could not find suggestion: {e}"}

        item = response.get("Item")
        if not item:
            return {"type": "error", "message": "Suggestion not found."}

        voter_uuid = self.entity.uuid if self.entity else self.uuid
        voters = item.get("voters", [])
        if voter_uuid in voters:
            return {"type": "error", "message": "You have already voted for this suggestion."}

        # Add vote
        voters.append(voter_uuid)
        new_votes = int(item.get("votes", 0)) + 1

        table.update_item(
            Key={"uuid": suggestion_uuid},
            UpdateExpression="SET votes = :v, voters = :vl",
            ExpressionAttributeValues={":v": new_votes, ":vl": voters},
        )

        return {
            "type": "vote_confirm",
            "message": f"Voted for: {item['text'][:60]}... ({new_votes} votes)",
            "suggestion_uuid": suggestion_uuid,
            "votes": new_votes,
        }

    @admin_only
    def review_suggestion(self, suggestion_uuid: str, status: str) -> dict:
        """Review a suggestion (admin only). Set status to approved or rejected.

        Args:
            suggestion_uuid: UUID of the suggestion.
            status: New status (approved, rejected, pending).

        Returns:
            dict with review confirmation.
        """
        if status not in ("approved", "rejected", "pending"):
            return {"type": "error", "message": "Status must be: approved, rejected, or pending"}

        from .aws_client import get_dynamodb_table

        table = get_dynamodb_table("SUGGESTION_TABLE")
        try:
            table.update_item(
                Key={"uuid": suggestion_uuid},
                UpdateExpression="SET #s = :s",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": status},
            )
        except Exception as e:
            return {"type": "error", "message": f"Failed to update suggestion: {e}"}

        return {
            "type": "review_confirm",
            "message": f"Suggestion {suggestion_uuid[:8]} marked as {status}.",
            "suggestion_uuid": suggestion_uuid,
            "status": status,
        }


handler = lambdaHandler(Entity)
