from app.core.database import Base, SessionLocal, engine
from app.services.auth_service import seed_default_admin
from app import models  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_default_admin(db)


if __name__ == "__main__":
    init_db()
    print("Database tables created and default admin ensured.")
