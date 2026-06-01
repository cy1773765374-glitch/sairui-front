from app.core.database import Base, SessionLocal, engine
from app.seed_agents import seed_agents
from app.services.auth_service import seed_default_admin
from app import models  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_default_admin(db)
        seed_agents(db)


if __name__ == "__main__":
    init_db()
    print("Database tables created, default admin ensured, and agents seeded.")
