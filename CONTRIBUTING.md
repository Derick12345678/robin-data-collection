# Contributing

## Setup and checks
Use the README quick start. Run `python -m unittest discover -s tests -v` before
opening a pull request. Tests must use synthetic examples and require no network,
Tor connection, model provider, or credentials.

## Branches and reviews
Use `feature/<topic>`, `fix/<topic>`, or `docs/<topic>` branches. Keep changes scoped
to one task, document behavior and verification, and request a teammate's review.
Repository branch protection and collaborator access must be configured by the team;
this scaffold does not claim that those settings are enabled.

## Data handling
Never commit raw findings, real source locators, credentials, HMAC keys, database
files, generated exports, or screenshots of collected content. Check the staged
diff before pushing. `.gitignore` helps prevent accidents but is not a secret scanner.
Do not include sensitive research targets in GitHub issues or PR descriptions.

## Changes requiring extra review
Changes to query scope, relevance rules, identifiers, duplicate handling, CSV
schema, or redaction rules need documented examples, expected effects, and review
by the team's data-quality owner. Update the data dictionary and policy version
when appropriate. No live collection should run from GitHub Actions.
