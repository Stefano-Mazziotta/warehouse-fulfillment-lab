from flask import Blueprint, jsonify, request

from integrations.application.receive_channel_event import ReceiveChannelEvent

from .channel_event_payload import InvalidChannelEvent, parse_channel_event


def create_webhook_blueprint(receive: ReceiveChannelEvent) -> Blueprint:
    blueprint = Blueprint("webhooks", __name__)

    @blueprint.post("/webhooks/sales-channel")
    def sales_channel():
        # Validate, persist the raw event, process through the inbox, acknowledge.
        # A duplicate event ID is acknowledged too, so the sender stops retrying it.
        try:
            event = parse_channel_event(request.get_json(silent=True))
        except InvalidChannelEvent as error:
            return jsonify(error=str(error)), 400
        outcome = receive.execute(event)
        return jsonify(eventId=event.event_id, outcome=outcome.value), 202

    return blueprint
