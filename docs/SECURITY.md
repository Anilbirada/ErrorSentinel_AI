# Security Architecture — RSR ErrorSentinel AI

## 1. Principles of Least Privilege & Safety

ErrorSentinel is engineered with defense-in-depth security:

1. **No Code Execution**:
   - Attachment files (PDF, DOCX, XLSX, CSV, JSON, XML, TXT, LOG) are parsed strictly as passive text data streams.
   - Macros, embedded scripts, and arbitrary binary executions are strictly prohibited and ignored.

2. **Attachment Sanitization**:
   - Filenames are sanitized against path traversal (`../`, `..\`) and illegal characters.
   - Executable extensions (`.exe`, `.bat`, `.cmd`, `.sh`, `.vbs`, `.ps1`, `.dll`, `.scr`, etc.) are blocked.
   - Strict size bounds (`MAX_ATTACHMENT_SIZE_MB`) prevent denial-of-service memory exhaustion.

3. **Secret Redaction**:
   - Passwords, OAuth tokens, refresh tokens, client secrets, and API keys are automatically scrubbed from logs via `SecretRedactionFilter`.
   - Never log full confidential email payload bodies.

4. **Credential Isolation**:
   - Credentials are read exclusively from environment variables or local `.env` files.
   - Sensitive tokens are excluded via `.gitignore`.
