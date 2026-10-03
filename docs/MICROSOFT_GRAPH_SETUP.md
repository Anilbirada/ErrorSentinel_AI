# Microsoft Entra and Graph setup

For a complete first-test procedure, including safe local configuration, API
preflight, success verification, and a failed-delivery test, see
[First Microsoft 365 live test](./FIRST_LIVE_TEST.md).

At a high level, the service requires an Entra app registration using
client-credentials authentication, Microsoft Graph mail-read and mail-send
application access, admin consent where applicable, and Exchange mailbox
scoping limited to the monitor and sender mailboxes. Do not use unscoped
tenant-wide mailbox access.

Microsoft recommends Exchange Online RBAC for Applications for new mailbox
scoping. RBAC grants are separate from unscoped Entra application permissions;
do not leave broad Entra mail app roles in place while expecting Exchange RBAC
to narrow them. If your organization uses Entra Graph `Mail.Read` and
`Mail.Send` application permissions, use a properly scoped Exchange
Application Access Policy and validate both mailbox identities. Consult the
current [Microsoft Exchange RBAC for Applications documentation](https://learn.microsoft.com/exchange/permissions-exo/application-rbac)
and the [first-test checklist](./FIRST_LIVE_TEST.md) for the distinction.

The client-credential token requests the Microsoft Graph `.default` scope.
Configuration is supplied locally through `.env`; never commit credentials or
send them through chat or issue trackers.
