from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()


# HEAD too: monday's health checker (userAgent MondayHealth) uses it.
@router.api_route('/', methods=['GET', 'HEAD'], response_class=PlainTextResponse)
@router.api_route('/health', methods=['GET', 'HEAD'], response_class=PlainTextResponse)
def health():
    return 'OK'
