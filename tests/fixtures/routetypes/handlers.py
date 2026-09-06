from starlette.responses import PlainTextResponse


async def plain_handler(request):
    return PlainTextResponse("plain")


async def mounted_handler(request):
    return PlainTextResponse("mounted")


async def socket_handler(websocket):
    await websocket.accept()
    await websocket.close()
