# cloudflared ingress for jobs.fezle.io

The Hetzner host (`168.119.58.28`) ingresses non-Fezle projects through one
`cloudflared` daemon. Fezle owns 80/443 directly via its Docker nginx; do **not**
touch Fezle's nginx/compose.

## Steps (on the server, as root)

1. Read `/root/SERVER_REGISTRY.md` and confirm `127.0.0.1:8095` is free
   (`ss -ltnp | grep 8095`). Pick another port if taken and update the systemd unit + this file.

2. Add an ingress rule to `/etc/cloudflared/config.yml`, **above** the catch-all
   `http_status:404` rule:

   ```yaml
   ingress:
     - hostname: jobs.fezle.io
       service: http://localhost:8095
     # ... existing rules ...
     - service: http_status:404
   ```

3. Route DNS through the tunnel (use the tunnel name from `config.yml`):

   ```bash
   cloudflared tunnel route dns <tunnel-name> jobs.fezle.io
   ```

4. Restart and verify:

   ```bash
   systemctl restart cloudflared
   systemctl status cloudflared --no-pager
   curl -sS https://jobs.fezle.io/api/health
   ```

5. Append a dated entry to
   `/opt/ops-registry/hosts/hetzner-168-119-58-28/CHANGELOG.md`.
