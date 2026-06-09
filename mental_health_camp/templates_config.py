import os
from starlette.templating import Jinja2Templates
from config import (
    APP_NAME, PRIMARY_COLOR, SECONDARY_COLOR, ACCENT_COLOR,
    PRIMARY_BG, PRIMARY_TEXT, PRIMARY_BTN, NAV_BG
)
from utils.csrf import get_or_create_csrf_token

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
_jinja2_templates = Jinja2Templates(directory=templates_dir)

context_processors = {
    "APP_NAME": APP_NAME,
    "PRIMARY_COLOR": PRIMARY_COLOR,
    "SECONDARY_COLOR": SECONDARY_COLOR,
    "ACCENT_COLOR": ACCENT_COLOR,
    "PRIMARY_BG": PRIMARY_BG,
    "PRIMARY_TEXT": PRIMARY_TEXT,
    "PRIMARY_BTN": PRIMARY_BTN,
    "NAV_BG": NAV_BG,
    "csrf_token": get_or_create_csrf_token,
}

_jinja2_templates.env.globals.update(context_processors)


class _TemplateResponseCompat:
    def __init__(self, jinja2_templates):
        self._templates = jinja2_templates

    def __getattr__(self, name):
        return getattr(self._templates, name)

    def TemplateResponse(self, *args, **kwargs):
        if len(args) >= 2 and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else kwargs.get("context", {})
            if context is None:
                context = {}
            request = context.get("request")
            return self._templates.TemplateResponse(
                request, name, context,
                status_code=kwargs.get("status_code", 200),
                headers=kwargs.get("headers"),
                media_type=kwargs.get("media_type"),
                background=kwargs.get("background"),
            )
        return self._templates.TemplateResponse(*args, **kwargs)


templates = _TemplateResponseCompat(_jinja2_templates)
