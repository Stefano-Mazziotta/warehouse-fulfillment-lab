import strawberry

from ..orders.reservation_type import ReservationType


@strawberry.type(name="RecordPickPayload")
class RecordPickPayload:

    reservation: ReservationType
