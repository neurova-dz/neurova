from app import create_app

app = create_app()

if __name__ == "__main__":
    # Werkzeug reloader can crash on Windows with WinError 10038 during reload.
    # Disable it for stable dev runs — after changing routes/views (e.g. app/routes/site.py),
    # stop and restart this process so Flask picks up new endpoints (otherwise url_for may BuildError).
    app.run(debug=True, use_reloader=False)
