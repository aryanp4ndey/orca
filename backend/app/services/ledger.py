"""Bounded store of recent query responses.

Backs ``GET /api/v1/evidence/{query_id}``: the frontend gets a light response
and can pull the full evidence chain on demand, which keeps the default payload
small on a weak connection without losing traceability.
"""

from __future__ import annotations

from collections import OrderedDict

from app.schemas.api import QueryResponse


class QueryLedger:
    def __init__(self, max_entries: int = 200) -> None:
        self._data: OrderedDict[str, QueryResponse] = OrderedDict()
        self._max = max_entries

    def put(self, response: QueryResponse) -> None:
        self._data[response.query_id] = response
        self._data.move_to_end(response.query_id)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def get(self, query_id: str) -> QueryResponse | None:
        return self._data.get(query_id)

    def recent(self, limit: int = 20) -> list[QueryResponse]:
        return list(self._data.values())[-limit:][::-1]

    def stats(self) -> dict:
        return {"stored_queries": len(self._data), "capacity": self._max}
