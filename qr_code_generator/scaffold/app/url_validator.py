from urllib.parse import urlparse

MAX_URL_LENGTH = 2048

BLOCKED_DOMAINS = {
    "evil.com",
    "malware.example.com",
    "phishing.example.com",
}


def is_blocked_domain(hostname: str | None) -> bool:
    if hostname is None:
        return True
    return hostname.lower() in BLOCKED_DOMAINS


def validate_url(url: str) -> str:
    """Format check, normalization, and blocklist validation."""
    if len(url) > MAX_URL_LENGTH:
        raise ValueError(f"URL exceeds max length of {MAX_URL_LENGTH}")

    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError("URL scheme must be http or https")

    if not parsed.hostname:
        raise ValueError("URL must have a hostname")

    if is_blocked_domain(parsed.hostname):
        raise ValueError(f"Domain '{parsed.hostname}' is blocked")

    scheme = "https"
    hostname = parsed.hostname.lower()
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    path = parsed.path.rstrip("/")

    normalized = f"{scheme}://{netloc}{path}"
    if parsed.query:
        normalized += f"?{parsed.query}"
    if parsed.fragment:
        normalized += f"#{parsed.fragment}"

    return normalized
