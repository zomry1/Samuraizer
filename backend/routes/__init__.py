"""
Samuraizer – Route blueprint registration.
"""

from backend.routes.analyze import bp as analyze_bp
from backend.routes.entries import bp as entries_bp
from backend.routes.chat import bp as chat_bp
from backend.routes.lists import bp as lists_bp
from backend.routes.search import bp as search_bp
from backend.routes.feeds import bp as feeds_bp
from backend.routes.settings import bp as settings_bp
from backend.routes.logs import bp as logs_bp


def register_blueprints(app):
    app.register_blueprint(analyze_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(lists_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(feeds_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(logs_bp)
