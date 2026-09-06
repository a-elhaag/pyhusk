"""Shared by both services."""

from pydantic import BaseModel


class Item(BaseModel):
    id: int
    name: str
