# API operations · fictional sample

This sample runbook belongs to an imaginary product named Atlas. It is included only to demonstrate EvidenceDesk and must not be treated as real operational policy.

## API key rotation

Rotate a production API key every 90 days, or immediately after a suspected leak. Create the replacement key before revoking the old one. Store the new key in the secret manager, deploy all dependent services, and verify successful requests in the API metrics dashboard. Revoke the old key only after the new key is confirmed across every service. Record the rotation ticket and the final revocation time.

## Authentication failures

An HTTP 401 response means the request has no valid credentials. Check whether the Authorization header uses the Bearer scheme and whether the key is active. An HTTP 403 response means the key was accepted but lacks the required permission. Do not print full API keys in logs or support tickets.

## Rate limits

The sample API allows 120 requests per minute per workspace. A 429 response includes a Retry-After header with the wait time in seconds. Clients should retry with exponential backoff and jitter, with a maximum of three attempts.
