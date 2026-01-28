"""Base repository class."""

from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from seh.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Base repository with common CRUD operations."""

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        """Initialize repository with a session.

        Args:
            session: SQLAlchemy session.
        """
        self.session = session

    def get_by_id(self, id: int) -> ModelT | None:
        """Get a record by its primary key.

        Args:
            id: Primary key value.

        Returns:
            Model instance or None if not found.
        """
        return self.session.get(self.model, id)

    def get_all(self) -> list[ModelT]:
        """Get all records.

        Returns:
            List of all model instances.
        """
        stmt = select(self.model)
        return list(self.session.scalars(stmt).all())

    def add(self, instance: ModelT) -> ModelT:
        """Add a new record.

        Args:
            instance: Model instance to add.

        Returns:
            The added instance.
        """
        self.session.add(instance)
        self.session.flush()
        return instance

    def add_all(self, instances: list[ModelT]) -> list[ModelT]:
        """Add multiple records.

        Args:
            instances: List of model instances to add.

        Returns:
            The added instances.
        """
        self.session.add_all(instances)
        self.session.flush()
        return instances

    def delete(self, instance: ModelT) -> None:
        """Delete a record.

        Args:
            instance: Model instance to delete.
        """
        self.session.delete(instance)
        self.session.flush()
