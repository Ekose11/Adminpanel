from flask import Blueprint, render_template, send_from_directory

personel_pwa = Blueprint(
    "personel_pwa",
    __name__,
    template_folder="templates",
    static_folder="static",
)


@personel_pwa.get("/personel")
@personel_pwa.get("/personel/")
def personel_app():
    return render_template("personel_pwa.html")


@personel_pwa.get("/personel/manifest.webmanifest")
def manifest():
    return send_from_directory(
        "static/personel-pwa",
        "manifest.webmanifest",
        mimetype="application/manifest+json",
    )


@personel_pwa.get("/personel/service-worker.js")
def service_worker():
    response = send_from_directory(
        "static/personel-pwa",
        "service-worker.js",
        mimetype="application/javascript",
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/personel/"
    return response
