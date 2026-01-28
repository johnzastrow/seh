"""Custom exception hierarchy for SolarEdge Harvest."""


class SEHError(Exception):
    """Base exception for all SolarEdge Harvest errors."""

    pass


class ConfigurationError(SEHError):
    """Error in application configuration."""

    pass


class APIError(SEHError):
    """Error communicating with the SolarEdge API."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize API error.

        Args:
            message: Error message.
            status_code: HTTP status code if available.
        """
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(APIError):
    """API rate limit exceeded."""

    def __init__(self, message: str = "API rate limit exceeded") -> None:
        super().__init__(message, status_code=429)


class DatabaseError(SEHError):
    """Error with database operations."""

    pass


class SyncError(SEHError):
    """Error during data synchronization."""

    pass
