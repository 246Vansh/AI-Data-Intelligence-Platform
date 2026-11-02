"""
The single explicit browser-origin allow-list.

Used both by the CORS middleware (backend/main.py) and by the auth
endpoints' Origin/CSRF check (backend/auth/routes.py), so the two can
never drift apart. Never add "*": CORS here is credentialed
(allow_credentials=True), and the session cookie must only ever be
honoured for these origins.
"""

ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)
