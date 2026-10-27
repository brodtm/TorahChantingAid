"""
Scroll-profile / column-map routes (`/api/scroll/*`).

Mounted onto the main `api` router from server.py via `register(api)`
so all existing endpoints keep their prefix and response shape.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from scroll_profiles import (
    list_profiles, get_profile, get_column, locate_column, get_line_at,
    DEFAULT_PROFILE,
)


class LocateColumnRequest(BaseModel):
    snippet: str
    profile: str = DEFAULT_PROFILE


class LineAtRequest(BaseModel):
    column: int
    y_fraction: float
    profile: str = DEFAULT_PROFILE


def register(api: APIRouter) -> None:
    """Attach the six scroll endpoints to the caller's router."""

    @api.get("/scroll/profiles")
    async def scroll_profiles_list():
        return list_profiles()

    @api.get("/scroll/profile/{name}")
    async def scroll_profile_meta(name: str):
        p = get_profile(name)
        if not p:
            raise HTTPException(404, f"Profile not found: {name}")
        return {
            "name": p.get("name"),
            "title": p.get("title"),
            "tradition": p.get("tradition"),
            "source": p.get("source"),
            "column_count": p.get("column_count", len(p.get("columns", []))),
            "books_covered": p.get("books_covered", []),
        }

    @api.get("/scroll/{name}/column/{n}")
    async def scroll_get_column(name: str, n: int):
        col = get_column(n, name)
        if not col:
            raise HTTPException(404, f"Column {n} not found in profile {name}")
        return col

    @api.post("/scroll/locate-column")
    async def scroll_locate_column(req: LocateColumnRequest):
        res = locate_column(req.snippet, req.profile)
        if not res:
            return None
        return res

    @api.post("/scroll/line-at")
    async def scroll_line_at(req: LineAtRequest):
        res = get_line_at(req.column, req.y_fraction, req.profile)
        if not res:
            raise HTTPException(404, "Column or profile not found")
        return res
