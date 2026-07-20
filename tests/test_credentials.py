import json

import pytest

from optionsbot.paper.credentials import (
    REQUIRED, load_credentials, load_env_file, load_from_aws,
)

ANGEL_SECRET = {
    "ANGELONE_API_KEY": "key123",
    "ANGELONE_CLIENT_ID": "A123456",
    "ANGELONE_PASSWORD": "9999",
    "ANGELONE_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
}


def test_aws_secret_maps_angelone_aliases():
    creds = load_from_aws("tradingbot/angel", runner=lambda args: json.dumps(ANGEL_SECRET))
    assert creds == {
        "SMARTAPI_KEY": "key123",
        "SMARTAPI_CLIENT_CODE": "A123456",
        "SMARTAPI_PIN": "9999",
        "SMARTAPI_TOTP_SECRET": "JBSWY3DPEHPK3PXP",
    }


def test_aws_secret_accepts_canonical_names():
    canonical = {k: "v" for k in REQUIRED}
    creds = load_from_aws("x", runner=lambda args: json.dumps(canonical))
    assert sorted(creds) == sorted(REQUIRED)


def test_aws_secret_missing_key_is_a_clear_error():
    partial = dict(ANGEL_SECRET)
    del partial["ANGELONE_TOTP_SECRET"]
    with pytest.raises(SystemExit, match="SMARTAPI_TOTP_SECRET"):
        load_from_aws("tradingbot/angel", runner=lambda args: json.dumps(partial))


def test_aws_secret_non_json_is_a_clear_error():
    with pytest.raises(SystemExit, match="not a JSON object"):
        load_from_aws("x", runner=lambda args: "plain-text-secret")


def test_aws_region_passed_through():
    seen = {}

    def runner(args):
        seen["args"] = args
        return json.dumps(ANGEL_SECRET)

    load_from_aws("tradingbot/angel", region="ap-south-1", runner=runner)
    assert "--region" in seen["args"] and "ap-south-1" in seen["args"]


def test_env_file_fallback_with_quotes_and_comments(tmp_path):
    p = tmp_path / "broker.env"
    p.write_text(
        'SMARTAPI_KEY="key123"\n'
        "SMARTAPI_CLIENT_CODE=A123456 # my client code\n"
        "SMARTAPI_PIN='9999'\n"
        "SMARTAPI_TOTP_SECRET=JBSWY3DPEHPK3PXP\n"
    )
    creds = load_env_file(p)
    assert creds["SMARTAPI_KEY"] == "key123"
    assert creds["SMARTAPI_CLIENT_CODE"] == "A123456"
    assert creds["SMARTAPI_PIN"] == "9999"


def test_missing_everything_mentions_both_options(tmp_path):
    with pytest.raises(SystemExit, match="aws-secret"):
        load_credentials(tmp_path / "nope.env", aws_secret=None)
