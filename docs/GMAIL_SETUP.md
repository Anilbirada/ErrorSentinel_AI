# Gmail API & OAuth Setup Guide — RSR ErrorSentinel AI

This guide walks you through configuring your personal or corporate Gmail account to enable email monitoring and automated alert delivery.

---

## 1. Dashboard Gmail connections

The dashboard connection flow uses a **Google Web application OAuth client**. It is separate from the legacy Desktop OAuth flow used by the CLI.

1. Enable the Gmail API in the Google Cloud project.
2. Configure the OAuth consent screen and add the users who may sign in while the app is in Testing.
3. Create an OAuth client with application type **Web application**.
4. Register both callback URLs below as **Authorized redirect URIs**. The URLs must exactly match the deployment environment and the values in its environment variables:

   Local development:
   - `http://localhost:8000/auth/google/callback`
   - `http://localhost:8000/auth/gmail/callback`

   Railway production (replace the hostname with the service's actual public domain):
   - `https://YOUR_RAILWAY_DOMAIN/auth/google/callback`
   - `https://YOUR_RAILWAY_DOMAIN/auth/gmail/callback`

5. Set these variables in the local `.env` file or Railway service variables. Do not commit populated values:

   ```ini
   GOOGLE_CLIENT_ID=
   GOOGLE_CLIENT_SECRET=
   GOOGLE_LOGIN_REDIRECT_URI=http://localhost:8000/auth/google/callback
   GOOGLE_REDIRECT_URI=http://localhost:8000/auth/gmail/callback
   SESSION_SECRET_KEY=
   TOKEN_ENCRYPTION_KEY=
   ```

   For Railway, use the production callback URLs instead. Keep both keys stable across restarts and replicas. Generate a URL-safe session key with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and a Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

6. Start ErrorSentinel and open its dashboard. Sign in with Google, then use **Gmail Connection → Connect Gmail** to authorize each mailbox. Connections and monitoring data are scoped to the signed-in Google identity. OAuth tokens are encrypted with `TOKEN_ENCRYPTION_KEY` before storage.

The dashboard requests only `openid`, `email`, `gmail.readonly`, and `gmail.send`. Gmail read access is required to scan messages; send access is currently used to send alerts from the connected mailbox. Google may require OAuth consent-screen verification before unrestricted external users can authorize restricted Gmail scopes.

Production requires persistent database storage (prefer PostgreSQL) and stable `SESSION_SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` values. Losing or changing the encryption key makes saved Gmail credentials unreadable. The SQLite database is suitable for local development, not ephemeral production storage.

OAuth callbacks use one-time, browser-bound state with a short expiration. Disconnect removes stored local credentials, marks the connection inactive, stops future monitoring, and requests Google token revocation. Existing monitoring history is retained.

## 2. Legacy CLI OAuth

The following Desktop OAuth setup remains available for existing CLI workflows and the legacy single-mailbox provider. It is not used by dashboard Gmail connections.

## 3. Prerequisites
- A Google / Gmail account.
- Access to the [Google Cloud Console](https://console.cloud.google.com/).

---

## 4. Google Cloud Project Setup

1. **Create Project**:
   - Go to Google Cloud Console.
   - Click **Select a project** -> **New Project**.
   - Name it `RSR-ErrorSentinel-AI` and click **Create**.

2. **Enable the Gmail API**:
   - Navigate to **APIs & Services** -> **Library**.
   - Search for `Gmail API`.
   - Click on **Gmail API** and click **Enable**.

3. **Configure OAuth Consent Screen**:
   - Go to **APIs & Services** -> **OAuth consent screen**.
   - Choose **External** (or **Internal** if using Google Workspace).
   - Fill in App name: `RSR ErrorSentinel AI` and User support email.
   - Under **Scopes**, add:
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.send`
   - Under **Test Users**, add your Gmail address (e.g. `your-email@gmail.com`).

4. **Create OAuth Client ID Credentials**:
   - Go to **APIs & Services** -> **Credentials**.
   - Click **Create Credentials** -> **OAuth client ID**.
   - Application type: **Desktop app**.
   - Name: `ErrorSentinel CLI Client`.
   - Click **Create**.
   - Click **Download JSON** and save the file as `credentials.json` in the root workspace `E:\ai agent\credentials.json`.

---

## 5. Legacy Environment Configuration

In your `.env` file, ensure the following parameters are configured:

```ini
EMAIL_PROVIDER=gmail
GMAIL_USER=me
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send
```

---

## 6. Legacy First-Time Authorization Flow

When you execute ErrorSentinel for the first time:

```bash
python main.py --run-now
```

1. A local browser window will open asking you to sign in with your Google Account.
2. Grant read and send permissions to ErrorSentinel.
3. Upon approval, OAuth tokens are securely saved locally to `token.json`.
4. Subsequent runs will automatically refresh tokens in the background without user interaction.
