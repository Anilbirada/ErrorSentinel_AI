# First Microsoft 365 live test

Use a non-production mailbox and a controlled test recipient if possible. This
checklist uses the real Microsoft Graph API only when you start the service and
run the monitoring job; unit tests never contact Microsoft 365.

## 1. Register the application

1. In the Microsoft Entra admin center, open **Identity → Applications → App
   registrations → New registration**.
2. Choose a descriptive name such as `RSR ErrorSentinel AI - test`, select
   **Accounts in this organizational directory only**, and register it.
3. Record the **Directory (tenant) ID** and **Application (client) ID** from
   the app's Overview page. Do not confuse the application ID with the
   Enterprise application's service-principal object ID.
4. Under **Certificates & secrets**, create a client secret with an expiry
   approved by your administrator. Copy its *value* into your organization's
   secret manager immediately; Entra only displays the value at creation.
   Never put it in source control, a ticket, or chat.

## 2. Grant only the required mail permissions

The agent uses app-only access with the Microsoft Graph `.default` scope. It
needs read access to the monitoring inbox and send access as the alert sender.

In **API permissions → Add a permission → Microsoft Graph → Application
permissions**, select `Mail.Read` and `Mail.Send`. An administrator must select
**Grant admin consent** and confirm the consent status.

### Restrict mailbox access before running the app

Do not run with unrestricted tenant-wide mailbox access. Select one supported
scoping method with your Exchange administrator and verify it before testing:

- **Recommended for a new setup: Exchange Online RBAC for Applications.**
  Create a resource scope containing only the monitoring mailbox and the
  alert-sender mailbox (one mailbox if they are the same), register the Entra
  service principal in Exchange Online, and assign the Exchange application
  roles for reading and sending mail against that scope. Follow Microsoft's
  current setup and validation procedure, including
  `Test-ServicePrincipalAuthorization`.
  **Important:** Exchange RBAC grants are independent of unscoped Entra
  application-role grants. Do not leave tenant-wide Graph `Mail.Read` or
  `Mail.Send` application grants in place while relying on RBAC scopes to
  restrict them. Have the administrator configure the app using the RBAC
  application roles and scoped assignments rather than a parallel unscoped
  grant.
- **If your organization requires the Entra Graph `Mail.Read` and `Mail.Send`
  application permissions above:** use an Exchange Application Access Policy
  scoped to a mail-enabled security group containing only the monitoring and
  sender mailboxes, and test both mailboxes with
  `Test-ApplicationAccessPolicy`. Application Access Policies are the older
  supported restriction mechanism; Microsoft recommends RBAC for Applications
  for new deployments. Do not combine the two methods assuming one will narrow
  the other's grants: unscoped grants are additive.

Microsoft references:

- [Exchange Online RBAC for Applications](https://learn.microsoft.com/exchange/permissions-exo/application-rbac)
- [Limit application permissions to specific Exchange Online mailboxes](https://learn.microsoft.com/graph/auth-limit-mailbox-access)

Ask your Exchange administrator to confirm that both the monitoring mailbox
and the sender mailbox are in scope, and that other mailboxes are not. `Mail.Send`
allows sending to configured recipients from the scoped sender; the recipient
does not need to be in the mailbox access scope.

## 3. Create and fill the local environment file

I checked the project folder: `.env` does not currently exist. From
`E:\ai agent`, run this exact PowerShell command to create it from the template:

```powershell
Copy-Item .env.example .env
```

Open `.env` in a local editor, not a shared chat or ticket. Set:

| Variable | Value |
| --- | --- |
| `MS_TENANT_ID` | Entra Directory (tenant) ID |
| `MS_CLIENT_ID` | Entra Application (client) ID |
| `MS_CLIENT_SECRET` | Client secret **value**, stored locally only |
| `MONITOR_MAILBOX` | Mailbox whose Inbox the agent will read |
| `ALERT_FROM_MAILBOX` | Mailbox the agent will send alerts from |
| `ALERT_RECIPIENTS` | One or more alert recipients, comma-separated |

Use a real, authorized test recipient. Keep `.env` out of source control; it is
already listed in `.gitignore`. Do not enable or configure an AI provider for
this deterministic error-code test. Keep attachment processing disabled unless
you specifically need to test attachments.

## 4. Start the service and check preflight

From the project root, run:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another PowerShell window, check health and configuration:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/preflight
```

`/api/health` is deliberately non-sensitive and reports service health only.
`/api/preflight` returns `status` and the **names only** of missing required
settings, never their values. Continue only when it says `ready`. If preflight
is `incomplete`, correct the named values in `.env` and restart the service.
`POST /api/run-now` also refuses to start when required settings are missing.
`ready` means the required local settings are present; it does not prove that
Entra consent, Exchange mailbox scoping, or credentials are valid.

## 5. Send and run the test

1. From a test mailbox, send a new email to `MONITOR_MAILBOX`. Put `ERR-9001`
   in the subject or body, for example:

   ```text
   Subject: ErrorSentinel live test ERR-9001

   Test diagnostic: operation failed with ERR-9001.
   ```

2. Trigger one monitoring run:

   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/run-now
   ```

   Save the returned `run_id`.
3. Confirm the alert arrived at every `ALERT_RECIPIENTS` address. Graph's
   successful `sendMail` response is the point at which the agent marks the
   delivery successful and updates the registries.
4. Check run history and delivery state:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8000/api/runs
   Invoke-RestMethod "http://127.0.0.1:8000/api/runs/<run_id>"
   Invoke-RestMethod "http://127.0.0.1:8000/api/runs/<run_id>/deliveries"
   ```

   Replace `<run_id>` with the returned ID. Expect run status `SUCCESS` and a
   delivery item with status `SUCCESS`.
5. Confirm report files exist:

   ```powershell
   Get-ChildItem .\reports\<run_id>.html, .\reports\<run_id>.json
   ```

6. Confirm `ERR-9001` was added to `data\existing_error_codes.txt`. The SQLite
   registry is also stored in `data\errorsentinel.db`. A later scan should
   classify this normalized code as known rather than send another new-code
   alert. It should no longer appear in `GET /api/errors/new`.

## 6. Verify failed delivery does not register a code

Perform this only with a disposable test code and controlled test mailboxes:

1. Leave mailbox read access working, but temporarily set
   `ALERT_FROM_MAILBOX` to an existing mailbox that is deliberately **outside**
   the application's approved send scope. Restart the service. Do not broaden
   the app's permissions to make this negative test work.
2. Send a new test email containing `ERR-9002` and run `POST /api/run-now`.
   The run should be `PARTIAL`; the delivery endpoint should report `FAILED`.
3. Confirm `ERR-9002` is absent from `data\existing_error_codes.txt` and has
   not been added to the database registry. It should remain visible in
   `GET /api/errors/new`, and the report should still exist.
4. Restore the authorized `ALERT_FROM_MAILBOX`, restart, and trigger another
   run without resending the original email. The persisted finding remains
   eligible, so the agent should send the alert and only then add `ERR-9002`
   to the registry.

If any result differs, stop the test and review
[troubleshooting](./TROUBLESHOOTING.md) and Graph/Exchange permission scope
before granting additional access.
