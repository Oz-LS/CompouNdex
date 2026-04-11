from flask import Blueprint

guidelines_bp = Blueprint("guidelines", __name__, url_prefix="/guidelines")

from . import routes  # noqa: F401, E402
