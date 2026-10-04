"""Synthetic search candidates; collection parses this file without running it."""


def retry_timeouts(sender, sleep, max_attempts=3):
    """Retry TimeoutError with bounded attempts and exponential backoff."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    for attempt in range(max_attempts):
        try:
            return sender()
        except TimeoutError:
            if attempt == max_attempts - 1:
                raise
            sleep(2**attempt)


def report_timeout(logger):
    """Log a TimeoutError description; this function performs no retry."""
    logger("A previous request raised TimeoutError")


def run_once(sender):
    """Handle TimeoutError after one call, without backoff or another attempt."""
    try:
        return sender()
    except TimeoutError:
        return None
