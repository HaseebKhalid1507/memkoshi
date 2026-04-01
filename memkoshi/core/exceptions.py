"""Mikoshi exception hierarchy."""


class MemkoshiError(Exception):
    """Base exception for Mikoshi."""
    pass


class MemkoshiStorageError(MemkoshiError):
    """Storage operation failed."""
    pass


class MemkoshiPipelineError(MemkoshiError):
    """Pipeline operation failed."""
    pass


class MemkoshiNotInitializedError(MemkoshiError):
    """Storage not initialized."""
    pass
