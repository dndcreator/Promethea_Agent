# Security Policy

## Supported Versions
Security fixes are applied to the latest main branch.

## Reporting a Vulnerability
Please do not open public issues for security reports.

Send details to your private security contact channel with:
- Affected component/file
- Reproduction steps / PoC
- Impact assessment
- Suggested fix (if any)

We will acknowledge within 72 hours and provide remediation status updates.

## Secrets Handling
- Never commit API keys, tokens, passwords.
- Use environment variables and `.env` (local only).
- Rotate exposed secrets immediately.
