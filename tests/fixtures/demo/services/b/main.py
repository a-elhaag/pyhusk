from fastapi import FastAPI

from common.models import Item
from common.reporting import fetch_report

app = FastAPI()


@app.get("/report")
async def report() -> Item:
    await fetch_report("http://example.invalid")
    return Item(id=1, name="report")
