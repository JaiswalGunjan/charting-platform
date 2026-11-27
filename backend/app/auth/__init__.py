"""Sign-in: Google (AUTH_MODE=google) or the built-in local user (AUTH_MODE=local, development and tests only).

Every route but /health and /auth/* needs a signed-in user (app/main.py); the browser holds a session cookie
(app.auth.sessions), and each request is counted for the user's activity stats (app.auth.activity)."""
