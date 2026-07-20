# 09 — EC2 Deployment Guide

Step-by-step: from no AWS account to this project running verified on a Mumbai EC2 instance with the static IP your broker will whitelist.

**What you're deploying today**: the backtester + dev environment (the live bot arrives in PLAN Phase 4 and will run on this same box). Deploying early has one real benefit — the Elastic IP gets allocated now, so broker whitelisting (docs/03) isn't blocked later. If you don't need the IP yet, running locally is cheaper; see §10 before deciding.

---

## 1. AWS account basics (once)

1. Create the AWS account; enable **MFA on the root user** immediately.
2. Create an IAM user (or IAM Identity Center user) with `AdministratorAccess` for daily use — never operate as root.
3. Set a **billing alarm**: Billing → Budgets → monthly budget (~$15) with an email alert. Infra costs must stay visible (see §10).
4. Pick region **ap-south-1 (Mumbai)** in the top-right console selector — closest to NSE/BSE, and the setup endorsed in the research.

## 2. Launch the instance

Console → EC2 → Launch instance:

| Setting | Value |
|---|---|
| Name | `optionsbot` |
| AMI | Ubuntu Server 24.04 LTS (64-bit x86) |
| Instance type | `t3.micro` (free-tier eligible first year; enough for a low-frequency bot) |
| Key pair | Create new → type **ED25519** → download `optionsbot.pem` |
| Network | Default VPC, **Auto-assign public IP: enable** |
| Security group | New: inbound **SSH (22) from "My IP" only**, nothing else inbound |
| Storage | 20 GiB gp3 |

Then on your Mac:

```bash
mkdir -p ~/.ssh && mv ~/Downloads/optionsbot.pem ~/.ssh/
chmod 400 ~/.ssh/optionsbot.pem
```

## 3. Allocate the Elastic IP (the broker-whitelist IP)

1. EC2 → Elastic IPs → **Allocate Elastic IP address** → Allocate.
2. Select it → Actions → **Associate** → choose the `optionsbot` instance.
3. Record the IP in `docs/decisions/infra.md`. This is the static IP you'll whitelist with the broker (docs/03). Treat it as precious: some brokers cap IP updates at once per week, so never release it casually.

## 4. Connect and harden

```bash
ssh -i ~/.ssh/optionsbot.pem ubuntu@<ELASTIC_IP>
```

On the box:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv git unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades   # enable automatic security patches
sudo timedatectl set-timezone Asia/Kolkata        # market hours in IST, logs in IST
```

Notes: Ubuntu's AMI already disables SSH password auth (key-only). Keep the security group as the firewall — SSH from your IP only. If your home IP changes, update the security-group rule, not the SSH config.

## 5. Get the code onto the box

**Option A — git (recommended; gives you history + easy redeploys).** On your Mac:

```bash
cd ~/Desktop/options
git init && git add -A && git commit -m "options algo: research, docs, backtester"
gh repo create options-algo --private --source=. --push
```

On EC2 (using a fine-grained GitHub token or `gh auth login`):

```bash
git clone https://github.com/<you>/options-algo.git ~/options
```

Redeploys are then `git pull` on the box.

**Option B — rsync (no git, fastest right now).** On your Mac:

```bash
rsync -avz -e "ssh -i ~/.ssh/optionsbot.pem" \
  --exclude .venv --exclude __pycache__ --exclude .pytest_cache --exclude data \
  ~/Desktop/options/ ubuntu@<ELASTIC_IP>:~/options/
```

## 6. Build and verify on the box

```bash
cd ~/options
python3 -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

**Deployment is verified when all tests pass** (76 as of this writing) — the same gate-2a hand-computed P&L check that guards your Mac now guards the box. If the counts differ between machines, stop and find out why before anything else.

## 7. Secrets layout (Phase 1+, before any broker API use)

```bash
mkdir -p ~/options/secrets && chmod 700 ~/options/secrets
touch ~/options/secrets/broker.env && chmod 600 ~/options/secrets/broker.env
```

`broker.env` holds `API_KEY=...`, `API_SECRET=...` etc. It is git-ignored (`secrets/` is in `.gitignore`); it never leaves the box, and it gets loaded by the systemd unit below via `EnvironmentFile=`. Never put credentials in code, config TOML, or the repo.

## 8. Broker whitelisting (Phase 1 gate)

Once the broker is chosen (PLAN Phase 0): register the Elastic IP in their API portal, complete OAuth app setup, then run the gate-1 verification from [SETUP.md](../SETUP.md) §7 — authenticate, refresh a token across a session boundary, pull quotes, raise a test alert — **from this box**.

## 9. Running the bot as a service (Phase 4 template — the bot doesn't exist yet)

When `optionsbot.bot` exists, install this unit so the bot survives reboots and crashes:

```ini
# /etc/systemd/system/optionsbot.service
[Unit]
Description=Options trading bot
After=network-online.target
Wants=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/options
EnvironmentFile=/home/ubuntu/options/secrets/broker.env
ExecStart=/home/ubuntu/options/.venv/bin/python -m optionsbot.bot --config config/default.toml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now optionsbot
journalctl -u optionsbot -f          # live logs
```

Two rules from docs/04 that the service design must respect: a restart must **reconcile positions against the broker before placing any order**, and repeated crash-restarts must page you (the `Restart=on-failure` loop is not a substitute for the alert channel).

## 10. Cost reality at ₹1 lakh capital — read before leaving it running

On-demand, 24/7, Mumbai (approx.): t3.micro ~$7.6/mo + 20 GiB gp3 ~$1.8/mo + public IPv4 ~$3.6/mo ≈ **$13/mo ≈ ₹1,100/mo ≈ ₹13k+/yr — about 13% of your capital**, far above the ~2–3%/yr infra target in PLAN Phase 0. Ways to stay honest:

1. **Free tier**: new AWS accounts get 750 hrs/mo of t3.micro for 12 months — effectively free compute in year one (the IPv4 charge may still apply).
2. **Don't run 24/7 before the bot exists.** For dev/backtesting, stop the instance when idle (a stopped instance costs only EBS + idle-IP pennies). Backtests can also just run on your Mac.
3. **Market-hours scheduling** (Phase 5+): EventBridge Scheduler rules to start the instance ~08:45 IST and stop ~16:00 IST on weekdays cut compute ~70%. The Elastic IP stays yours while stopped.
4. Re-check the math at each capital milestone (docs/07) — fixed costs shrink as a share as capital grows.

## 11. Post-deploy checklist

```
[ ] MFA on root; IAM user in use; billing alarm set
[ ] Instance in ap-south-1, SSH restricted to your IP
[ ] Elastic IP associated and recorded in docs/decisions/infra.md
[ ] Timezone Asia/Kolkata; unattended-upgrades on
[ ] Code deployed; .venv built; FULL TEST SUITE GREEN ON THE BOX
[ ] secrets/ created with 700/600 perms (empty until a broker is chosen)
[ ] Stop-when-idle habit or scheduler in place (cost target ~2-3%/yr)
```
