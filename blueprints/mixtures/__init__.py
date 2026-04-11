from flask import Blueprint

mixtures_bp = Blueprint("mixtures", __name__, url_prefix="/mixtures")

from . import routes  # noqa: F401, E402
