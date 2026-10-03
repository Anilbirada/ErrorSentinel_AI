# Gmail API & OAuth Setup Guide — RSR ErrorSentinel AI

This guide walks you through configuring your personal or corporate Gmail account to enable email monitoring and automated alert delivery.

---

## 1. Prerequisites
- A Google / Gmail account.
- Access to the [Google Cloud Console](https://console.cloud.google.com/).

---

## 2. Google Cloud Project Setup

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

## 3. Environment Configuration

In your `.env` file, ensure the following parameters are configured:

```ini
EMAIL_PROVIDER=gmail
GMAIL_USER=me
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
GMAIL_SCOPES=https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.send
```

---

## 4. First-Time Authorization Flow

When you execute ErrorSentinel for the first time:

```bash
python main.py --run-now
```

1. A local browser window will open asking you to sign in with your Google Account.
2. Grant read and send permissions to ErrorSentinel.
3. Upon approval, OAuth tokens are securely saved locally to `token.json`.
4. Subsequent runs will automatically refresh tokens in the background without user interaction.
