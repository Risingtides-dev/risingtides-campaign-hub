"""Webhook endpoints for external integrations."""
from flask import Blueprint, jsonify

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/api/webhooks")


@webhooks_bp.post("/notion")
def notion_webhook():
    # Implemented in Phase 3
    return jsonify({"error": "Not implemented"}), 501
