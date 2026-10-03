# Troubleshooting Guide — RSR ErrorSentinel AI

## 1. Common Issues & Solutions

### Issue: "GMAIL_CREDENTIALS_FILE not found"
**Cause:** `credentials.json` is missing from the workspace root.
**Solution:**
1. Download OAuth credentials from Google Cloud Console.
2. Save as `credentials.json` in `E:\ai agent\`.
3. Or test in offline mode using `python main.py --demo` or `EMAIL_PROVIDER=demo`.

### Issue: "A monitoring run is already active"
**Cause:** The background scheduler or a user triggered a run while another is still processing.
**Solution:**
ErrorSentinel prevents overlapping runs to ensure data integrity and avoid duplicate alerts. Wait for the active cycle to finish or check `/api/status`.

### Issue: "Alert delivery failed; registry unchanged"
**Cause:** Email provider rejected the outbound email (e.g. invalid recipient or expired token).
**Solution:**
This is the **Mandatory Transaction Rule** in action. The registry was not updated so no error signatures were lost. Fix email credentials/network and retry the run.
