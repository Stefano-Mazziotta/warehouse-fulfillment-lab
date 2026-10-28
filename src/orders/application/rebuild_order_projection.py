from .order_event_source import OrderEventSource
from .order_projection import OrderProjection
from .project_order_event import ProjectOrderEvent


class RebuildOrderProjection:
    """Wipe the read model and replay the recorded history into it.

    The history is the transactional outbox, which commits with the business change, so it
    is exactly as complete as PostgreSQL itself. Replaying uses the same projector as the
    live consumer; it needs no inbox because duplicate and stale events are no-ops there.
    Running it while the live consumer is active is safe for the same reason, except for
    the instant of the wipe: do it when readers can tolerate an empty projection.
    """

    def __init__(self, projection: OrderProjection, source: OrderEventSource) -> None:
        self._projection = projection
        self._projector = ProjectOrderEvent(projection)
        self._source = source

    def run(self) -> int:
        self._projection.reset()
        replayed = 0
        for message in self._source.events():
            self._projector.project(message)
            replayed += 1
        return replayed
