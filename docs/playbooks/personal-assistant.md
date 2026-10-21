# Personal Assistant Capabilities

Personal productivity uses the existing `CapabilityService -> ToolRegistry ->
Observation -> ActionService` path. It does not introduce another Agent loop,
account service, or tool protocol. External services may still be added through
the existing MCP integration.

## Implemented Scope

| Capability | Interface | Boundary |
| --- | --- | --- |
| Mail search | `mail.search` | Read-only IMAP, bounded headers, Unicode TEXT search where supported by the server |
| Mail read | `mail.read` | UID + UIDVALIDITY, BODY.PEEK, bounded text, attachment metadata only |
| Mail send/reply | `mail.send` | Plain text, To/Cc/Bcc, optional In-Reply-To, exact Runtime confirmation |
| Calendar inventory | `calendar.list` | Calendars belonging to the configured CalDAV principal |
| Calendar search/read | `calendar.search`, `calendar.read` | Explicit timezone offsets, bounded interval, UID and revision information |
| Calendar create/delete | `calendar.create`, `calendar.delete` | Confirmation; create-only PUT, ETag-conditional deletion; no recurring-series deletion |
| Reservations | `travel_booking` skill + current provider/browser tools | Task guidance, not a universal ticket API or a guarantee of completed checkout |

No account is required at startup. The Registry retains tool definitions, but
catalogs and exact capability inspection report missing configuration/dependencies
as unavailable. Probing readiness does not connect to a mailbox or calendar:
configured is not the same as authenticated or healthy.

## Configure An Account

Sign in, open **Settings -> Sensitive Runtime Settings -> Personal accounts**,
enter the account details, and use **Save Sensitive Settings**. **Remove account**
clears that account's local connection fields; it does not revoke a credential at
the provider or erase mail/events already sent or created.

The same settings can be edited in the current user's ignored
`config/users/<user_id>/secrets.env`:

```dotenv
MAIL__IMAP_HOST=imap.example.com
MAIL__IMAP_PORT=993
MAIL__SMTP_HOST=smtp.example.com
MAIL__SMTP_PORT=465
MAIL__SMTP_SECURITY=ssl
MAIL__USERNAME=you@example.com
MAIL__PASSWORD=your_app_password
MAIL__FROM=you@example.com

CALENDAR__URL=https://calendar.example.com/dav/
CALENDAR__USERNAME=your_calendar_username
CALENDAR__PASSWORD=your_calendar_app_password
```

These personal-account keys deliberately do **not** inherit root `.env` or
process-environment values. Otherwise a new user could inherit the operator's
mailbox. They reuse the existing per-user env writer and redacted settings API;
passwords never appear in status responses, tool arguments, or portable archives.
Empty form fields retain existing values; removal is explicit.

IMAP uses TLS on port 993 by default. SMTP supports implicit TLS (`ssl`, default
465) or required STARTTLS (`starttls`, default 587); it never falls back to
plaintext. Configure the correct port when changing an existing connection.
Use a provider-issued app password where supported. This implementation does
not implement Google/Microsoft OAuth or bypass providers that prohibit password
authentication. Use an authorized provider-specific MCP integration in that case.

Mail uses Python's standard library. Calendar integration additionally requires:

```bash
python -m pip install -e ".[productivity]"
```

CalDAV uses the maintained `caldav` and `icalendar` libraries. Use the canonical
HTTPS URL. Discovery stays on that origin, redirects are rejected, certificate
verification remains enabled, and responses are capped at 8 MiB. The existing
network sandbox policy also applies; a private/self-hosted server may require
an operator-approved network-policy change.

## Execution And Confirmation

Reading does not mark messages read. Search returns the mailbox's UIDVALIDITY;
pass it unchanged to `mail.read` so a rebuilt mailbox cannot silently resolve a
stale UID to a different message. HTML is reduced to text without executing it
or loading images. Attachments are not downloaded or opened by these tools.

Sending and calendar mutations are separate external-write tools. In addition
to their declared Runtime policy, implementations require the exact scoped
confirmation grant before changing external state. Background jobs do not get
implicit consent. Workbench titles/summaries use the existing presentation
contract, not tool-name branches in React.

SMTP acceptance is **not** proof of delivery. Partial recipient rejection stays
visible. If the connection is lost during submission, the outcome remains
unknown and no transport retry is performed; inspect the provider before
resending. This is not exactly-once delivery. An in-flight network operation
cannot be undone by cancelling the local task.

Calendar create requires a fresh UUID and conditional `If-None-Match: *` PUT;
it never sends meeting invitations. Delete requires the exact ETag from
`calendar.read`, checks that revision again, and sends `If-Match`. Servers that
do not supply/enforce these standard preconditions cannot offer the same
concurrency guarantees. Updating events, invitation management, recurring-series
mutations, native mail OAuth, mail attachment transfer, and server-side drafts
are not implemented by this initial pack.

## Reservations And External Providers

The lazily loaded `travel_booking` skill reuses existing search, workspace browser,
Task/Run, confirmation, and Observation mechanisms. It collects actual constraints,
compares observed offers, distinguishes estimated prices from live inventory,
and requires verification after an ambiguous submission. It grants no additional
tool permissions and embeds no supplier-specific site selectors.

There is no cross-platform ticketing or payment protocol. Actual inventory,
booking, cancellation, login, and payment depend on the selected provider's API
or website. Add a provider through the existing MCP/extension path and declare
read operations separately from purchases. Do not expose provider secrets as
tool parameters or claim that loading the skill establishes a reservation.

## References And Tests

OpenClaw similarly separates reusable task guidance from executable integration:
its [Himalaya skill](https://github.com/openclaw/openclaw/blob/main/skills/himalaya/SKILL.md)
uses IMAP/SMTP tooling, while its [Google Workspace skill](https://github.com/openclaw/openclaw/blob/main/skills/gog/SKILL.md)
uses an OAuth-authorized CLI. Promethea retains its own native Runtime execution
and MCP boundaries rather than invoking another Agent.

`tests/test_productivity_tools.py` checks isolation, readiness, read-only access,
exact consent, ambiguous sends, TLS, CalDAV scoping, conditional writes, timezones,
and skill authority. The real-library test runs when the productivity extra is
installed. `tests/test_productivity_settings_browser.py` checks configuration and
removal through synthetic API responses. These tests do not send real messages,
contact personal calendars, or place orders; provider acceptance testing still
requires a disposable account and explicit operator consent.
