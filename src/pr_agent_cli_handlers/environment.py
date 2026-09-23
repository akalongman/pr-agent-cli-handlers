"""Read handler settings from the process environment, build the CLI's environment, and redact credentials.

Keep handler settings in the environment rather than in PR-Agent's settings object: PR-Agent merges a
repository's .pr_agent.toml into its settings, and that file has no path into the process environment.
"""
import math
import re
import shlex
from typing import Iterable, Mapping

from pr_agent_cli_handlers.errors import CliHandlerError

HANDLER_VAR = "PR_AGENT_CLI_HANDLER"
BINARY_VAR = "PR_AGENT_CLI_BINARY"
EXTRA_ARGS_VAR = "PR_AGENT_CLI_EXTRA_ARGS"
TIMEOUT_VAR = "PR_AGENT_CLI_TIMEOUT"
PASS_ENV_VAR = "PR_AGENT_CLI_PASS_ENV"

# Pass these to every CLI: process basics, locale, temporary and XDG directories, proxies and CA bundles.
BASE_ENV_NAMES = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "LANG", "LANGUAGE", "TZ", "TMPDIR", "TEMP", "TMP",
    "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS",
})
BASE_ENV_PREFIXES = ("LC_",)
CREDENTIAL_NAME_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")
MIN_SECRET_LENGTH = 8
REDACTED = "[REDACTED]"
_ENV_NAME = re.compile(r"[A-Za-z0-9_]+")


def read_binary(environ: Mapping[str, str], default: str) -> str:
    """Return PR_AGENT_CLI_BINARY, or ``default`` when it is unset or blank."""
    return environ.get(BINARY_VAR, "").strip() or default


def read_extra_args(environ: Mapping[str, str]) -> list[str]:
    """Return PR_AGENT_CLI_EXTRA_ARGS split the way a POSIX shell splits words."""
    raw = environ.get(EXTRA_ARGS_VAR, "")
    try:
        return shlex.split(raw)
    except ValueError as e:
        raise CliHandlerError(f"cannot parse {EXTRA_ARGS_VAR}: {e}") from e


def read_timeout(environ: Mapping[str, str], fallback: float) -> float:
    """Return PR_AGENT_CLI_TIMEOUT in seconds, or ``fallback`` when it is unset or blank."""
    raw = environ.get(TIMEOUT_VAR, "").strip()
    if not raw:
        return float(fallback)
    try:
        value = float(raw)
    except ValueError as e:
        raise CliHandlerError(f"{TIMEOUT_VAR} must be a positive number of seconds, got {raw!r}") from e
    if not math.isfinite(value) or value <= 0:
        raise CliHandlerError(f"{TIMEOUT_VAR} must be a positive number of seconds, got {raw!r}")
    return value


def read_pass_env(environ: Mapping[str, str]) -> list[str]:
    """Return the variable names listed in PR_AGENT_CLI_PASS_ENV, trimmed, without empty entries."""
    names = []
    for entry in environ.get(PASS_ENV_VAR, "").split(","):
        name = entry.strip()
        if not name:
            continue
        if not _ENV_NAME.fullmatch(name):
            raise CliHandlerError(f"{PASS_ENV_VAR} contains an invalid variable name: {name!r}")
        names.append(name)
    return names


def build_child_env(environ: Mapping[str, str], adapter_names: Iterable[str],
                    pass_names: Iterable[str]) -> dict[str, str]:
    """Return the subset of ``environ`` a CLI may see: base names, the adapter's names and the passed names."""
    allowed = BASE_ENV_NAMES | frozenset(adapter_names) | frozenset(pass_names)
    return {name: value for name, value in environ.items()
            if name in allowed or name.startswith(BASE_ENV_PREFIXES)}


def credential_values(environ: Mapping[str, str], credential_names: Iterable[str]) -> list[str]:
    """Return credential values worth redacting, longest first.

    Include the adapter's credential variables and every variable whose name contains TOKEN, KEY, SECRET or
    PASSWORD in any case, skipping values shorter than MIN_SECRET_LENGTH so short flags such as "1" survive.
    """
    names = frozenset(credential_names)
    values = {
        value for name, value in environ.items()
        if len(value) >= MIN_SECRET_LENGTH
        and (name in names or any(marker in name.upper() for marker in CREDENTIAL_NAME_MARKERS))
    }
    return sorted(values, key=len, reverse=True)


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of each secret in ``text`` with REDACTED, longest secret first."""
    for secret in sorted(set(secrets), key=len, reverse=True):
        if secret and secret in text:
            text = text.replace(secret, REDACTED)
    return text
