# Primary-source claim screening (no AI model)

## Finding definition
A finding must be a primary-source item asserting an **existing** organizational
exposure or an offer of a specific existing organizational dataset. The supporting
page text must establish an affected organization or identifiable organizational
dataset. Publisher/provider names, hypothetical targets, and hacking-related words
alone do not establish that relationship.

The owner approved this narrower definition after rejecting the three readable
pages in `relevance-validation-02`. Scope version `1.5-primary-source-claims` and
screening version `primary-claims-1` record the change. The original query registry
remains disabled. Historical capture snapshots are preserved under their original
scope; they are not silently reclassified into a new dataset.

## Rules and roles
The deterministic classifier distinguishes primary announcements, specific dataset
listings, secondary reporting, educational content, service advertisements,
directories, and unknown intent. It treats an existing possession/exposure/sale
assertion separately from an offer to obtain information in the future.

A victim must occupy a supported relationship in the same bounded clause as the
claim, such as an organization associated with customer/employee data or a directly
identified affected organization. A provider's name in a byline is not the victim.
A dataset identifier requires organizational context. Personal records alone do
not qualify. A capitalized word or a private alias-registry match alone is
insufficient. Negated, hypothetical, attributed, and quoted statements cannot
stand in for a primary assertion.

Search metadata is used only to prioritize page requests. Ambiguous or excluded
metadata spends no page budget. A fetched page is assessed again: a promising
search-result title cannot substitute for a missing claim in the page text.
Quoted HTML and navigation/header/footer boilerplate are excluded from extracted
claim text. Mixed or unsupported phrasing defers for review rather than guessing.

These are conservative English-language patterns, not semantic understanding.
They can miss valid claims or encounter unsupported layouts/wording. Neither a
rule label nor a seller assertion verifies an exposure or the existence/authenticity
of records. A human-reviewed pilot must measure usefulness before expansion.

## Evidence and privacy
Durable observations store finite intent/claim/role/basis labels, bounded evidence
counts, and keyed pseudonyms for inferred victims, dataset identifiers, and
supporting clauses. Registry-confirmed victim aliases remain distinct from inferred
victim roles. Raw role names and evidence quotations are not written to the database,
normal review exports, release CSV, or logs.

Supporting quotes exist only in the signed temporary private review context. They
must occur in the retained context and match the committed evidence pseudonyms.
If clipping/redaction removes the support, the candidate is deferred and its target
assertions are cleared. Existing 24-hour memory expiry and process-exit deletion
still apply. The HTML UI renders evidence as text and shows the claim basis and
specificity alongside the full bounded context.

Inclusion requires page-text evidence, the current claim policy, a supported primary
intent/claim relationship, actual source/privacy/date/duplicate review, and two
consistent distinct reviewer IDs. If a reviewer enters an organization name it must
match a supported victim pseudonym; a publisher/provider cannot be substituted.
Leaving the label blank accepts a single detected victim after review, or leaves
the organization unknown when there are multiple/no supported victims.
The CSV includes finite intent, claim type, specificity, role, evidence count,
assessment basis, and rule version. It retains the unverified-source-claim label.
A dataset-only claim may have an unknown organization. Raw quotes never enter it.

## Regression and cached-page checks
`tests/fixtures/primary_claims.synthetic.json` contains positive and negative
examples. The three owner-reported negatives cover:

| Case | Rule assessment | Qualifying victim/dataset evidence |
|---|---|---|
| News article about a financial-aid breach | Secondary reporting; exclude | None for a primary-source finding |
| Cell-phone forensics guide/service promotion | Service advertisement; exclude | None |
| Generic corporate leak retrieval offer | Capability/service advertisement; exclude | None |

The same rules were applied locally to the three already-cached page contexts.
All three were excluded (one secondary report and two service advertisements),
with zero new source requests. A finite reassessment report is kept in the ignored
pilot output directory. It is a rule assessment, not fabricated human votes.
`relevance-validation-02` is now quarantined following the owner's assessment; all
58 discovery records and the original audit trail are preserved.

Validation passed: 96 unit/regression tests and the pinned MCP integration with
Docker networking disabled. Synthetic success fixtures now assert explicit
first-hand, target-specific claims rather than merely mentioning a breach. The
integration still calls no model. These checks do not establish live precision.

## Next collection
No new live collection was dispatched for this change. The revised scope and
collector fingerprint invalidate earlier pilot promotion. A future small pilot
needs a new exclusively created, dated policy file, such as:

```bash
python3 scripts/collect.py validation-policy --policy data/live/primary-claim-policy.json
python3 scripts/collect.py run --validation --enrich \
  --policy data/live/primary-claim-policy.json --run-id primary-claim-validation-01
```

Run these when starting that next pilot; they have not been executed as part of
this repair. Do not renew or overwrite prior policies. Larger batches remain
blocked until 10â€“20 actually reviewed unique pages achieve at least 80% relevance
under the matching code and scope. Do not weaken the gate or manufacture positive
findings to increase yield.

AI models and model-provider APIs remain disabled. No AI model charges are incurred
by this collection workflow.
