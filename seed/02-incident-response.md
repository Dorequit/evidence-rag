# Incident response · fictional sample

This example describes an imaginary engineering team. Adapt every step to your own organization before use.

## Severity and escalation

Declare a SEV-1 incident when the service is unavailable for all customers or there is evidence of customer data exposure. The on-call engineer creates an incident channel, pages the incident commander, and opens a timeline within 10 minutes. The incident commander assigns an operations lead and a communications lead. Escalate to the security lead immediately if data exposure is suspected.

## Customer updates

For SEV-1 incidents, publish an initial status update within 30 minutes of declaration. Publish a new update every 30 minutes until service is restored. Include observed impact, current mitigation, and the time of the next update. Avoid speculating about the root cause before it is verified.

## Resolution and review

The incident commander marks the incident resolved after customer impact stops and monitoring stays stable for 30 minutes. A blameless review is due within five working days. The review records the timeline, contributing factors, detection gaps, and owners for follow-up actions.
