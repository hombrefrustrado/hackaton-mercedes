from flask import Flask

app = Flask(
    __name__,
    template_folder="templates"
)

# Manual CORS setup for all requests
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "*"
    return response

# Import and register Blueprints
from .routes.web import web_bp
from .routes.api import api_bp

app.register_blueprint(web_bp)
app.register_blueprint(api_bp)
