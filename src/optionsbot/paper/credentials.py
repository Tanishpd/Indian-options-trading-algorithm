"""Credential loading for the paper/live session.

Sources, in order of preference:
1. AWS Secrets Manager (--aws-secret NAME or OPTIONSBOT_AWS_SECRET env var) —
   fetched via the AWS CLI so no boto3 dependency; on EC2 an instance role
   with secretsmanager:GetSecretValue is enough, no stored AWS keys.
2. A local dotenv-style file (secrets/broker.env), overridable by process env.

The secret's JSON keys may use either the bot's canonical names or the
ANGELONE_* names, which are mapped below. Values never touch disk or logs.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

REQUIRED = ("SMARTAPI_KEY", "SMARTAPI_CLIENT_CODE", "SMARTAPI_PIN", "SMARTAPI_TOTP_SECRET")

_ALIASES = {
    "ANGELONE_API_KEY": "SMARTAPI_KEY",
    "ANGELONE_CLIENT_ID": "SMARTAPI_CLIENT_CODE",
    "ANGELONE_CLIENT_CODE": "SMARTAPI_CLIENT_CODE",
    "ANGELONE_PASSWORD": "SMARTAPI_PIN",   # SmartAPI logs in with the PIN
    "ANGELONE_PIN": "SMARTAPI_PIN",
    "ANGELONE_TOTP_SECRET": "SMARTAPI_TOTP_SECRET",
}


def _canonical(raw: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = _ALIASES.get(key.upper(), key.upper())
        if name in REQUIRED and str(value).strip():
            out[name] = str(value).strip()
    return out


def _aws_bin() -> str:
    """Resolve the aws CLI even under minimal PATHs (nohup, systemd, cron)."""
    from shutil import which

    for candidate in (which("aws"), "/opt/homebrew/bin/aws",
                      "/usr/local/bin/aws", "/usr/bin/aws"):
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit(
        "aws CLI not found — install it or add it to PATH "
        "(credentials are fetched from AWS Secrets Manager)"
    )


def _run_aws(args: list[str]) -> str:
    proc = subprocess.run([_aws_bin(), *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(
            f"aws CLI failed: {proc.stderr.strip() or proc.stdout.strip()} — "
            "check `aws sts get-caller-identity`, the secret name, and (on EC2) "
            "that the instance role grants secretsmanager:GetSecretValue"
        )
    return proc.stdout


def load_from_aws(
    secret_id: str, region: str | None = None, runner: Callable[[list[str]], str] = _run_aws
) -> dict[str, str]:
    args = ["secretsmanager", "get-secret-value", "--secret-id", secret_id,
            "--query", "SecretString", "--output", "text"]
    if region:
        args += ["--region", region]
    raw = runner(args).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SystemExit(
            f"secret {secret_id!r} is not a JSON object of key/value pairs — "
            f"expected keys like {list(_ALIASES)[:2]} or {list(REQUIRED)}"
        ) from None
    creds = _canonical(data)
    missing = [k for k in REQUIRED if k not in creds]
    if missing:
        raise SystemExit(
            f"secret {secret_id!r} is missing {missing} — present keys map to "
            f"{sorted(creds)} (accepted aliases: {sorted(_ALIASES)})"
        )
    return creds


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(
            f"{path} not found and no --aws-secret given. Either pass "
            "--aws-secret <name> (e.g. tradingbot/angel) / set OPTIONSBOT_AWS_SECRET, "
            f"or copy config/broker.env.example to {path} and fill it in."
        )
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip()      # tolerate inline comments
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]                       # tolerate dotenv-style quoting
        env[k.strip()] = v
    return _canonical(env)


def load_credentials(
    secrets_file: Path,
    aws_secret: str | None = None,
    aws_region: str | None = None,
) -> dict[str, str]:
    if aws_secret:
        return load_from_aws(aws_secret, aws_region)
    creds = {**load_env_file(secrets_file), **_canonical(dict(os.environ))}
    missing = [k for k in REQUIRED if not creds.get(k)]
    if missing:
        raise SystemExit(f"missing credential(s) in {secrets_file}: {', '.join(missing)}")
    return creds


def load_optional_secret(
    secret_id: str,
    region: str | None = None,
    runner: Callable[[list[str]], str] | None = None,
) -> dict[str, str] | None:
    """Fetch a JSON secret, returning None (not an error) if it doesn't exist
    or the CLI fails — used for optional channels like Telegram alerts."""
    args = ["secretsmanager", "get-secret-value", "--secret-id", secret_id,
            "--query", "SecretString", "--output", "text"]
    if region:
        args += ["--region", region]
    try:
        raw = (runner or _run_aws)(args).strip()
        data = json.loads(raw)
    except (SystemExit, json.JSONDecodeError):
        return None
    return {k.upper(): str(v).strip() for k, v in data.items() if str(v).strip()}
