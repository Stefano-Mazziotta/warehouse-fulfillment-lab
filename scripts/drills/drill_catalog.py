from drill_allocation import DRILL as ALLOCATION_RACE
from drill_carrier import DRILL as CARRIER_TIMEOUT
from drill_crash import DRILL as CRASH_BEFORE_ACK
from drill_edi import DRILL as DUPLICATE_EDI
from drill_ordering import DRILL as OUT_OF_ORDER_EVENTS
from drill_reconcile import DRILL as LOST_WEBHOOK
from drill_valkey import DRILL as VALKEY_DOWN
from drill_webhook import DRILL as DUPLICATE_WEBHOOK

CATALOG = [
    ALLOCATION_RACE, CARRIER_TIMEOUT, DUPLICATE_WEBHOOK, OUT_OF_ORDER_EVENTS,
    CRASH_BEFORE_ACK, LOST_WEBHOOK, VALKEY_DOWN, DUPLICATE_EDI,
]
