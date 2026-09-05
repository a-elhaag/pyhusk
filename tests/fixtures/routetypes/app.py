"""Every route shape the probe must handle, in one app."""

from fastapi import Depends, FastAPI, WebSocket
from starlette.routing import Mount, Route

from handlers import mounted_handler, plain_handler, socket_handler
from providers import outer_dependency


def build() -> FastAPI:
    application = FastAPI()

    @application.get("/decorated")
    def decorated(value: str = Depends(outer_dependency)) -> dict[str, str]:
        return {"value": value}

    @application.websocket("/ws")
    async def websocket_route(websocket: WebSocket) -> None:
        await socket_handler(websocket)

    # Plain Starlette route: has .endpoint but no .dependant.
    application.router.add_route("/plain", plain_handler, methods=["GET"])

    application.router.routes.append(
        Mount("/sub", routes=[Route("/inner", mounted_handler, methods=["GET"])])
    )
    return application


app = build()
