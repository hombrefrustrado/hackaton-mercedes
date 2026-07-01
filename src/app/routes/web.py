from flask import Blueprint, render_template

web_bp = Blueprint("web", __name__)

@web_bp.route("/")
def index():
    return render_template("index.html")

@web_bp.route("/pilar1")
def pilar1():
    return render_template("pilar1.html")

@web_bp.route("/pilar2")
def pilar2():
    return render_template("pilar2.html")

@web_bp.route("/pilar3")
def pilar3():
    return render_template("pilar3.html")
