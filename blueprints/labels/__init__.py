from flask import Blueprint

labels_bp = Blueprint("labels", __name__, url_prefix="/labels")

from . import routes  # noqa: F401, E402
