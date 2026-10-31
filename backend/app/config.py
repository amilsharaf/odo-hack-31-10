import os

# Postgres is the intended database. For a quick local run without Postgres:
#   DATABASE_URL=sqlite:///./dev.db
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://brightloop:brightloop@localhost:5432/brightloop"
)
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me-in-production-0123456789")
TOKEN_TTL_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", "480"))
RESET_TTL_MINUTES = int(os.getenv("RESET_TTL_MINUTES", "60"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", FRONTEND_URL).split(",")
# Run the billing sweep in the background every N minutes (0 = off, use the button/endpoint).
BILLING_AUTORUN_MINUTES = int(os.getenv("BILLING_AUTORUN_MINUTES", "0"))
# Exposes the captured outgoing mail at /api/dev/mails so reset links can be used in a demo.
DEV_MAILBOX = os.getenv("DEV_MAILBOX", "false").lower() == "true"
