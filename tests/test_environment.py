import math
import os

import pytest

from pr_agent_cli_handlers.environment import (
    BINARY_VAR,
    CREDENTIAL_NAME_MARKERS,
    EXTRA_ARGS_VAR,
    PASS_ENV_VAR,
    REDACTED,
    TIMEOUT_VAR,
    build_child_env,
    credential_values,
    read_binary,
    read_extra_args,
    read_pass_env,
    read_timeout,
    redact,
)
from pr_agent_cli_handlers.errors import CliHandlerError

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/u",
    "LC_ALL": "C.UTF-8",
    "HTTPS_PROXY": "http://proxy:3128",
    "GITHUB_TOKEN": "ghs_sentinel_github",
    "GITLAB__PERSONAL_ACCESS_TOKEN": "glpat-sentinel-gitlab",
    "CI_JOB_TOKEN": "sentinel-ci-job",
    "OPENAI_API_KEY": "sk-sentinel-openai",
    "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-sentinel",
    "EXTRA_ONE": "extra-value",
    "UNRELATED": "x",
}


def test_read_binary_uses_the_variable_or_the_default():
    assert read_binary({}, "claude") == "claude"
    assert read_binary({BINARY_VAR: "  "}, "claude") == "claude"
    assert read_binary({BINARY_VAR: "/opt/bin/claude"}, "claude") == "/opt/bin/claude"


def test_read_extra_args_shell_splits_the_variable():
    assert read_extra_args({}) == []
    assert read_extra_args({EXTRA_ARGS_VAR: "--verbose --foo 'a b'"}) == ["--verbose", "--foo", "a b"]


def test_read_extra_args_names_the_variable_when_it_cannot_be_split():
    with pytest.raises(CliHandlerError, match=EXTRA_ARGS_VAR):
        read_extra_args({EXTRA_ARGS_VAR: "--foo 'unbalanced"})


def test_read_timeout_falls_back_when_unset_or_blank():
    assert read_timeout({}, 120) == 120.0
    assert read_timeout({TIMEOUT_VAR: " "}, 120) == 120.0
    assert read_timeout({TIMEOUT_VAR: "2.5"}, 120) == 2.5


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "nan", "inf", "-inf", "1e309"])
def test_read_timeout_rejects_values_that_are_not_positive_finite_numbers(raw):
    with pytest.raises(CliHandlerError, match=TIMEOUT_VAR):
        read_timeout({TIMEOUT_VAR: raw}, 120)


@pytest.mark.parametrize("fallback", [
    0, -1, -0.5, "0", "-1", "abc", "", " ", None, True, math.nan, math.inf, -math.inf, "nan", "inf", "1e309",
    pytest.param(10**400, id="int-too-large-for-float"),
])
def test_read_timeout_rejects_a_fallback_that_is_not_a_positive_finite_number(fallback):
    with pytest.raises(CliHandlerError, match=r"config\.ai_timeout"):
        read_timeout({}, fallback)
    with pytest.raises(CliHandlerError, match=r"config\.ai_timeout"):
        read_timeout({TIMEOUT_VAR: " "}, fallback)


@pytest.mark.parametrize("fallback", [0, -1, math.inf, math.nan, "abc", None])
def test_read_timeout_prefers_a_valid_variable_over_an_invalid_fallback(fallback):
    assert read_timeout({TIMEOUT_VAR: "30"}, fallback) == 30.0


def test_read_timeout_accepts_an_int_or_a_numeric_string_fallback():
    for fallback, expected in [(120, 120.0), ("45.5", 45.5), (" 90 ", 90.0), ("1e3", 1000.0)]:
        value = read_timeout({}, fallback)
        assert value == expected
        assert type(value) is float


def test_read_pass_env_trims_names_and_skips_empty_entries():
    assert read_pass_env({}) == []
    assert read_pass_env({PASS_ENV_VAR: " EXTRA_ONE, ,EXTRA_TWO,"}) == ["EXTRA_ONE", "EXTRA_TWO"]


@pytest.mark.parametrize("raw", ["EXTRA-ONE", "A B", "PATH;rm"])
def test_read_pass_env_rejects_invalid_names(raw):
    with pytest.raises(CliHandlerError, match=PASS_ENV_VAR):
        read_pass_env({PASS_ENV_VAR: raw})


def test_build_child_env_keeps_base_adapter_and_passed_names_only():
    env = build_child_env(PARENT, {"CLAUDE_CODE_OAUTH_TOKEN"}, ["EXTRA_ONE"])

    assert env == {
        "PATH": "/usr/bin",
        "HOME": "/home/u",
        "LC_ALL": "C.UTF-8",
        "HTTPS_PROXY": "http://proxy:3128",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-sentinel",
        "EXTRA_ONE": "extra-value",
    }


def test_credential_values_cover_adapter_names_and_credential_like_names_of_useful_length():
    parent = {**PARENT, "SHORT_TOKEN": "abc", "my_api_key": "lowercase-key-value"}

    values = credential_values(parent, {"EXTRA_ONE"})

    assert set(values) == {
        "ghs_sentinel_github", "glpat-sentinel-gitlab", "sentinel-ci-job", "sk-sentinel-openai",
        "sk-ant-oat-sentinel", "lowercase-key-value", "extra-value",
    }
    assert values == sorted(values, key=len, reverse=True)


def test_redact_replaces_every_occurrence_and_prefers_the_longest_secret():
    text = "a sk-ant-oat-sentinel b sk-ant-oat-sentinel-long c sk-ant-oat-sentinel"

    assert redact(text, ["sk-ant-oat-sentinel", "sk-ant-oat-sentinel-long"]) == (
        f"a {REDACTED} b {REDACTED} c {REDACTED}")
    assert redact("nothing here", ["sk-ant-oat-sentinel"]) == "nothing here"


def test_no_credential_like_variable_reaches_a_test():
    # Collect names only, so a failure never prints a value from the developer's or CI's environment.
    names = sorted(name for name in os.environ if any(marker in name.upper() for marker in CREDENTIAL_NAME_MARKERS))
    assert names == []
