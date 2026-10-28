import strawberry


@strawberry.type(name="PageInfo")
class PageInfoType:

    has_next_page: bool
    end_cursor: str | None
