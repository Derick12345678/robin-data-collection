# Sanitization policy — baseline-1

## Implemented
- Extract plain text, suppress script/style bodies, normalize Unicode and whitespace.
- Remove unwanted control characters.
- Replace detected email addresses, phone-like strings, IPv4-like strings, and
  explicitly labelled password/API-key/secret/token values with category markers.
- Replace source URLs and content identifiers with keyed HMAC IDs.
- Defend exported text against spreadsheet formula interpretation.
- Keep raw values out of normal error output, the database, and CSV exports.

## Required team decisions before real collection
Document the research scope; permitted identifiers; rules for names, usernames,
addresses, financial identifiers, and contextual details; retention period; access
owners; source retracing needs; and the authorized dataset destination.

## Limitations and review
These patterns can miss personal information or secrets and can redact innocent
numbers. All rows are pending_review. No automated relevance classifier, general
PII detector, residual-sensitivity guarantee, or approval command is implemented.
Review content and context using a second team member before sharing. Record approval
in a controlled review log; never treat renaming a CSV as evidence of review.

Changing the key breaks cross-batch matching. Keep it out of Git and outputs. HMAC
IDs are pseudonyms and should still be handled as potentially sensitive metadata.
