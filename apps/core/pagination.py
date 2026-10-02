from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """?page=2&page_size=50 - capped so a client cannot ask for everything at once."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
