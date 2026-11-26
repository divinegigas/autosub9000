"""User-facing errors. Every failure the user can see should be one of these,
with a short friendly message and an optional hint. Details go to the log."""

from __future__ import annotations


class AutoSubError(Exception):
    def __init__(self, message: str, hint: str = "", details: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.details = details

    def __str__(self) -> str:
        return self.message + (f"\n{self.hint}" if self.hint else "")


class Cancelled(AutoSubError):
    def __init__(self):
        super().__init__("Cancelled.")


class MissingBinary(AutoSubError):
    pass


class ModelMissing(AutoSubError):
    pass


def friendly(exc: BaseException) -> AutoSubError:
    """Convert any exception into an AutoSubError for display."""
    if isinstance(exc, AutoSubError):
        return exc
    import traceback

    details = "".join(traceback.format_exception(exc))
    if isinstance(exc, PermissionError):
        return AutoSubError("Permission denied.",
                            f"AutoSub9000 can't access {getattr(exc, 'filename', '') or 'a file'}. "
                            "Check the folder permissions or choose another output folder.", details)
    if isinstance(exc, FileNotFoundError):
        return AutoSubError("A file could not be found.", str(exc), details)
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return AutoSubError("The disk is full.", "Free some space or choose another output folder.", details)
    return AutoSubError("Something went wrong.",
                        "Open the log panel for technical details.", details)
