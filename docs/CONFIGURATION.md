# Configuration Reference — RSR ErrorSentinel AI

All system settings are configured via environment variables or a `.env` file in the workspace root.

## 1. Application Settings

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_NAME` | string | `RSR ErrorSentinel AI` | Application display name |
| `APP_ENV` | string | `development` | `development`, `production`, `test`, `demo` |
| `HOST` / `APP_HOST` | string | `0.0.0.0` | Bind IP address for server |
| `PORT` / `APP_PORT` | int | `8000` | HTTP port for dashboard and REST API |
| `LOG_LEVEL` | string | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## 2. Email Providers

| Variable | Type | Default | Description |
|---|---|---|---|
| `EMAIL_PROVIDER` | string | `gmail` | Active provider: `gmail`, `microsoft_graph`, `demo` |
| `GMAIL_USER` | string | `me` | Gmail account alias |
| `GMAIL_CREDENTIALS_FILE` | string | `credentials.json` | Google OAuth client secrets file |
| `GMAIL_TOKEN_FILE` | string | `token.json` | Cached OAuth token path |
| `MS_TENANT_ID` | string | `""` | Microsoft Entra Tenant ID |
| `MS_CLIENT_ID` | string | `""` | Microsoft Entra App Client ID |
| `MS_CLIENT_SECRET` | string | `""` | Microsoft Entra Client Secret |
| `MONITOR_MAILBOX` | string | `""` | Monitored inbox address |
| `ALERT_FROM_MAILBOX` | string | `""` | Alert sender mailbox address |
| `ALERT_RECIPIENTS` | string | `""` | Comma-separated alert email recipients |

---

## 3. Concurrency & Performance

| Variable | Type | Default | Description |
|---|---|---|---|
| `MAX_EMAIL_WORKERS` | int | `5` | Maximum concurrent email fetching threads |
| `MAX_ATTACHMENT_WORKERS`| int | `5` | Maximum concurrent attachment processing threads |
| `MAX_ATTACHMENT_SIZE_MB`| int | `25` | Max allowed attachment file size in MB |
| `MONITOR_INTERVAL_MINUTES`| int | `30` | Automatic schedule interval for APScheduler |
| `ENABLE_EMAIL_ATTACHMENTS` | bool | `true` | Whether to download & parse email attachments |
