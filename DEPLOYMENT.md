# Deployment

## Local Deployment

Use the development Compose file when you want to run the full stack on your own machine without the production image-pull and HTTPS setup.

### Prerequisites

- Docker Engine
- Docker Compose v2

### Local Environment File

Create `.env` at the repository root:

```dotenv
DB_PASSWORD=your_local_database_password
SECRET_KEY=your_local_django_secret_key
JWT_SECRET_KEY=your_local_jwt_secret_key
REDIS_PASSWORD=
DJANGO_ENV=development
```

Generate secrets locally if needed:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### Start the Local Stack

From the repository root:

```bash
docker compose build
docker compose up -d
```

The local stack uses [docker-compose.yaml](/home/yuyash/Workplace/AutoForex/docker-compose.yaml), builds images from the checked-out source, mounts the backend source code into the containers, and exposes HTTP only on port `80`.

### Initialize and Verify

Run these once after the first startup:

```bash
docker compose exec backend python manage.py createsuperuser
docker compose ps
docker compose logs -f
```

Default local endpoints:

- Frontend: `http://localhost`
- Backend API: `http://localhost/api`
- Django admin: `http://localhost/admin`
- Direct backend: `http://localhost:8000`

### Stop or Reset

```bash
docker compose down
docker compose down -v
```

Use `docker compose down -v` only when you intentionally want to delete the local PostgreSQL and Redis data.

## Production Deployment

The `Build and Deploy` GitHub Actions workflow builds Docker images, copies `docker-compose.prod.yaml` and `nginx/` to the host, and runs `docker compose pull && docker compose up -d`.

### Required GitHub Secrets

- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`
- `SSH_PRIVATE_KEY`
- `SERVER_HOST`
- `SERVER_USER`
- `DEPLOY_PATH`
- `SSH_PORT` (optional, defaults to `22`)

### First-Time Host Setup

Before the first deployment, prepare the production host:

1. Install Docker Engine and Docker Compose v2.
2. Point your DNS records to the server and open inbound ports `80` and `443`.
3. Create the deployment directory and add a production `.env` file there.
4. Issue the initial Let's Encrypt certificate before relying on the HTTPS Nginx config.

Use this `.env` shape on the host at `<DEPLOY_PATH>/.env`:

```dotenv
DOCKERHUB_USERNAME=your-dockerhub-user
DB_PASSWORD=generate-a-strong-postgres-password
SECRET_KEY=generate-a-django-secret-key
JWT_SECRET_KEY=generate-a-different-jwt-secret-key
REDIS_PASSWORD=optional-redis-password
ALLOWED_HOSTS=www.yourdomain.com
```

Generate secrets locally if needed:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "import secrets; print(secrets.token_urlsafe(64))"
openssl rand -base64 48
```

Notes:

- `JWT_SECRET_KEY` must be set in production and must differ from `SECRET_KEY`.
- `DB_PASSWORD` must be correct before the first `docker compose up -d`. The PostgreSQL image uses it when initializing the database volume; changing it later requires an explicit password rotation procedure inside PostgreSQL.

### Initial Certificate Issuance

The production Nginx config references real certificate files at
`/etc/letsencrypt/live/<domain>/`, so Nginx cannot start until a certificate
exists. Bootstrap the first certificate **inside a container that uses the
same volume mounts as the stack** (`certbot/conf` → `/etc/letsencrypt`,
`certbot/www` → `/var/www/certbot`).

> **Important:** Do not issue the certificate on the host with a host
> `--config-dir`. Doing so bakes host-absolute paths (e.g.
> `/opt/auto-forex/certbot/conf`) and a `standalone` authenticator into the
> renewal config. Inside the `certbot` container that directory is mounted at
> `/etc/letsencrypt`, so the stored paths no longer resolve and
> `certbot renew` silently skips the certificate — it eventually expires even
> though the container is running. Issuing in-container with the **webroot**
> challenge writes container-relative paths and `authenticator = webroot`, so
> the `certbot` service renews it automatically.

On the server:

```bash
cd <DEPLOY_PATH>
mkdir -p certbot/conf certbot/www logs
export DOMAIN=www.yourdomain.com
export EMAIL=you@example.com
```

1. Create a throwaway self-signed certificate so Nginx can boot and serve the
   ACME HTTP-01 challenge on port 80:

   ```bash
   mkdir -p "certbot/conf/live/$DOMAIN"
   docker run --rm -v "$PWD/certbot/conf:/etc/letsencrypt" \
     --entrypoint openssl certbot/certbot \
     req -x509 -nodes -newkey rsa:2048 -days 1 \
     -keyout "/etc/letsencrypt/live/$DOMAIN/privkey.pem" \
     -out "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" \
     -subj "/CN=$DOMAIN"
   ```

2. Start Nginx only — it now boots with the dummy certificate and serves the
   challenge path:

   ```bash
   docker compose -f docker-compose.prod.yaml up -d nginx
   ```

3. Delete the dummy certificate and request the real one via the **webroot**
   challenge:

   ```bash
   rm -rf "certbot/conf/live/$DOMAIN" \
          "certbot/conf/archive/$DOMAIN" \
          "certbot/conf/renewal/$DOMAIN.conf"

   docker run --rm \
     -v "$PWD/certbot/conf:/etc/letsencrypt" \
     -v "$PWD/certbot/www:/var/www/certbot" \
     certbot/certbot certonly --webroot -w /var/www/certbot \
     -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --no-eff-email
   ```

4. Bring up the full stack and reload Nginx so it serves the real certificate:

   ```bash
   docker compose -f docker-compose.prod.yaml up -d
   docker exec nginx nginx -s reload
   ```

Notes:

- Steps 1–2 exist only to break the chicken-and-egg problem (Nginx needs a
  certificate to start; the webroot challenge needs Nginx running). The dummy
  certificate is discarded in step 3.
- Ports `80` and `443` must be reachable from the internet for the HTTP-01
  challenge and normal traffic.
- After the first issuance, the repository's `certbot` service renews the
  certificate on a 12-hour loop and Nginx reloads every 6 hours to pick up the
  new files.
- Verify automatic renewal end to end with a dry run:

  ```bash
  docker exec certbot certbot renew --webroot -w /var/www/certbot --dry-run
  ```

### Deploying with GitHub Actions

After the host is prepared:

1. Push to `main`.
2. The workflow creates required directories under `DEPLOY_PATH`, uploads the production Compose and Nginx files, validates that `<DEPLOY_PATH>/.env` exists, then deploys.
3. Verify the deployed services and TLS certificate on the host if this is the first run.
