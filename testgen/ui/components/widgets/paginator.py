from testgen.ui.components.utils.component import component


def paginator(
    count: int,
    page_size: int,
    page_index: int = 0,
    key: str = "testgen:paginator",
) -> bool:
    """
    Testgen component to display pagination arrows.

    # Parameters
    :param count: total number of items being paginated
    :param page_size: number of items displayed per page
    :param page_index: index of initial page displayed, default=0 (first page)
    :param key: unique key to give the component a persisting state
    """

    return component(
        id_="paginator",
        key=key,
        default=page_index,
        props={"count": count, "pageSize": page_size, "pageIndex": page_index},
    )
