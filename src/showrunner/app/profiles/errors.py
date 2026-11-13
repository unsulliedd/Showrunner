"""Errors raised by profile handling."""

from __future__ import annotations


class ProfileError(Exception):
    """Base class of profile errors."""


class ProfileNotFoundError(ProfileError):
    pass


class ProfileExistsError(ProfileError):
    pass


class ReadOnlyProfileError(ProfileError):
    """A built-in profile cannot be changed, renamed or deleted."""


class InvalidProfileNameError(ProfileError):
    pass


class UnreadableProfileError(ProfileError):
    """The file is not JSON or not a profile at all; single bad values never cause this."""
