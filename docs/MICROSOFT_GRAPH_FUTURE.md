# Microsoft Graph Migration Architecture — RSR ErrorSentinel AI

## 1. Provider Swapping Architecture

ErrorSentinel's core business logic is completely decoupled from email provider details via the abstract `EmailProvider` interface:

```python
class EmailProvider(ABC):
    def authenticate(self) -> bool: ...
    def list_messages(self, ...) -> list[EmailMessage]: ...
    def get_message(self, message_id: str) -> Optional[EmailMessage]: ...
    def download_attachment(self, ...) -> Path: ...
    def send_alert(self, ...) -> bool: ...
```

---

## 2. Transitioning to Microsoft 365 / Microsoft Graph

When transitioning from Gmail in development to Microsoft Graph in production:

1. Register an application in **Microsoft Entra ID (Azure AD)**.
2. Grant application permissions for `Mail.Read` and `Mail.Send`.
3. In your production `.env`, change:
   ```ini
   EMAIL_PROVIDER=microsoft_graph
   MS_TENANT_ID=your-tenant-uuid
   MS_CLIENT_ID=your-app-client-uuid
   MS_CLIENT_SECRET=your-client-secret-value
   MONITOR_MAILBOX=monitored-shared-inbox@yourdomain.com
   ALERT_FROM_MAILBOX=alerts@yourdomain.com
   ALERT_RECIPIENTS=team@yourdomain.com
   ```
4. No core monitoring, extraction, registry, or alerting code requires modification.
