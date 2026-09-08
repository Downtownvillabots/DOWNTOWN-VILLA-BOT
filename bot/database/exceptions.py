# bot/database/exceptions.py
"""
Custom exceptions for the database system.
These are used to handle specific errors gracefully.
"""

class DatabaseError(Exception):
    """Base exception for all database-related errors."""
    pass

class DatabaseConnectionError(DatabaseError):
    """Raised when a connection to MongoDB fails."""
    pass

class DatabaseNotFoundError(DatabaseError):
    """Raised when a requested database is not registered."""
    pass

class DatabaseQueryError(DatabaseError):
    """Raised when a database operation (query, insert, etc.) fails."""
    pass
