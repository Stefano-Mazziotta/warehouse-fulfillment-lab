import strawberry

from ..page_info_type import PageInfoType
from .order_type import OrderType


@strawberry.type(name="OrderConnection")
class OrderConnectionType:

    nodes: list[OrderType]
    page_info: PageInfoType
