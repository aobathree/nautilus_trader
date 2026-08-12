class JQuantsError(Exception):
    """
    Raised when the J-Quants API returns a non-retryable error, or when
    retries are exhausted.
    """

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"J-Quants API error (HTTP {status}): {message}")
        self.status = status
        self.message = message
