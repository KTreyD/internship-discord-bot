import html as html_lib
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")


def strip_tags(raw_html: str) -> str:
    return html_lib.unescape(_TAG_RE.sub(" ", raw_html)).strip()


# Shared session across all fetchers for connection reuse (~60 ATS slugs
# hit this in one run).
_SESSION = requests.Session()

# (connect timeout, read timeout) in seconds. Every requests.get in the
# repo used to have no timeout at all - one unresponsive host could hang
# the entire daily run indefinitely.
DEFAULT_TIMEOUT = (5, 20)

_RETRY_BACKOFF = (1, 2, 4)


def get_json(url, *, params=None, retries=3):
    """GETs `url` and returns the parsed JSON body, or None on final failure.

    Retries on timeouts, connection errors, 429, and 5xx, honoring
    Retry-After when present, with 1/2/4s backoff otherwise.
    """
    attempts = max(1, retries)
    last_error = None

    for attempt in range(attempts):
        try:
            response = _SESSION.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e
            log.warning("Request to %s failed (%s), attempt %d/%d", url, e, attempt + 1, attempts)
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as e:
                    log.warning("Response from %s was not valid JSON: %s", url, e)
                    return None

            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    if attempt < attempts - 1:
                        time.sleep(delay)
                        continue
                log.warning("Request to %s returned %s, attempt %d/%d", url, response.status_code, attempt + 1, attempts)
            else:
                log.warning("Request to %s returned %s", url, response.status_code)
                return None

        if attempt < attempts - 1:
            time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])

    log.error("Giving up on %s after %d attempts (%s)", url, attempts, last_error)
    return None


def get_text(url, *, retries=3):
    """GETs `url` and returns the response body text, or None on final failure."""
    attempts = max(1, retries)
    last_error = None

    for attempt in range(attempts):
        try:
            response = _SESSION.get(url, timeout=DEFAULT_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e
            log.warning("Request to %s failed (%s), attempt %d/%d", url, e, attempt + 1, attempts)
        else:
            if response.status_code == 200:
                return response.text
            if response.status_code == 429 or response.status_code >= 500:
                last_error = f"HTTP {response.status_code}"
            else:
                log.warning("Request to %s returned %s", url, response.status_code)
                return None

        if attempt < attempts - 1:
            time.sleep(_RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)])

    log.error("Giving up on %s after %d attempts (%s)", url, attempts, last_error)
    return None
