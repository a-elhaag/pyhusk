from fastapi import Depends, FastAPI

from common.models import Item

from .security import current_user

app = FastAPI()


@app.get("/items/{item_id}")
def read_item(item_id: int, user: str = Depends(current_user)) -> Item:
    return Item(id=item_id, name=user)
