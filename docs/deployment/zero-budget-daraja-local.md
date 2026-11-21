# Zero-budget local Daraja sandbox

This is a local development workflow. It uses the developer's computer, Docker Compose, a local PostgreSQL volume, and a temporary Cloudflare Quick Tunnel. It does not create a cloud database or hosting service.

## Prerequisites

- Linux (tested workflow target: Ubuntu/Zorin OS family)
- Docker Engine with the Docker Compose v2 plugin
- Python 3
- curl
- A Daraja developer application with **Lipa Na M-Pesa Sandbox** enabled
- Daraja sandbox consumer key, consumer secret, shortcode, and passkey

Do not use production credentials or real customer funds.

## Bootstrap

From the repository root:

    bash scripts/setup-local-daraja-sandbox.sh

The script:
- reads Daraja credentials without echoing them,
- generates a random local PostgreSQL password,
- generates a high-entropy callback token,
- generates a Fernet key for phone-number encryption,
- writes a local .env file with restrictive permissions (0600),
- starts PostgreSQL, API, and worker using Docker Compose,
- checks API and database readiness.

The script refuses to overwrite an existing .env file. It does not print secrets. The .env file is gitignored; never commit it, upload it, or paste its contents into a support request.

If Docker is not installed, install Docker Engine and the Compose plugin using the official Docker instructions for your Linux distribution, then rerun the script. Do not run the script with sudo unless your Docker installation specifically requires it; adding your account to the docker group has security implications equivalent to root access.

## Publish a temporary callback endpoint

Install `cloudflared` using Cloudflare's official installation instructions. In a second terminal, run:

    cloudflared tunnel --url http://localhost:8000

Cloudflare prints a temporary HTTPS URL ending in `.trycloudflare.com`. It changes when the Quick Tunnel is restarted and works only while the process remains running.

Edit the local .env file and set:

    FRINGEPAY_DARAJA_CALLBACK_URL=https://YOUR-TUNNEL.trycloudflare.com/v1/webhooks/daraja?token=THE_CALLBACK_SECRET_FROM_DOTENV

Use the exact callback secret already generated in .env. Do not generate a different one for the URL. Save the file, then recreate the API and worker containers:

    docker compose up -d --force-recreate api worker

Keep Docker Compose and the tunnel process running while testing.

## Verify

    docker compose ps
    curl --fail http://127.0.0.1:8000/health
    curl --fail http://127.0.0.1:8000/ready
    docker compose logs --tail=100 api worker

Use the API's OpenAPI page at http://127.0.0.1:8000/docs to inspect the available endpoints. A successful readiness check proves local API/database connectivity, not Daraja credentials or end-to-end payment success.

## Security notes

A Quick Tunnel makes the local API reachable from the public internet by anyone who knows the temporary URL. The Daraja callback route checks its configured token, but do not expose development/admin endpoints or use this tunnel for production. Do not share the URL publicly. Cloudflare describes Quick Tunnels as temporary testing/development tunnels with no uptime guarantee; the URL stops working when the tunnel process stops.

The callback URL contains a secret query parameter. Avoid screenshots and logs containing it. The application disables Uvicorn access logs in Compose, but inspect any additional proxy or local logs before sharing them.

## Stop and clean up

Stop services but keep the database volume:

    docker compose down

To permanently delete the local PostgreSQL data as well:

    docker compose down -v

Only use the second command if you intentionally want to erase the local test database. To remove local credentials, securely delete .env after stopping the services.

## Scope

This setup is for Daraja sandbox integration testing only. It is not a production deployment, does not guarantee availability, and does not establish regulatory authorization. Live payment processing remains disabled.
