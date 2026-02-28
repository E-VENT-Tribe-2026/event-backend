from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models here so Alembic can detect schema changes
# from app.models.user import User
# from app.models.event import Event