# Production Deployment Guide — RSR ErrorSentinel AI

## 1. Docker Deployment

ErrorSentinel includes a production-ready `Dockerfile` and `docker-compose.yml`.

### Build & Run via Docker Compose:
```bash
docker-compose up -d --build
```

### Build & Run standalone container:
```bash
docker build -t rsr-errorsentinel:latest .
docker run -d -p 8000:8000 --env-file .env -v $(pwd)/data:/app/data rsr-errorsentinel:latest
```

---

## 2. Production Service (Systemd on Linux)

Create `/etc/systemd/system/errorsentinel.service`:

```ini
[Unit]
Description=RSR ErrorSentinel AI Monitoring Agent
After=network.target

[Service]
User=sentinel
WorkingDirectory=/opt/errorsentinel
ExecStart=/opt/errorsentinel/.venv/bin/python main.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/errorsentinel/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now errorsentinel
```

---

## 3. Production PostgreSQL Migration

To use PostgreSQL instead of SQLite:
```ini
DATABASE_URL=postgresql://sentinel_user:secure_password@localhost:5432/errorsentinel
```
No code changes required; SQLAlchemy handles the dialect automatically.
