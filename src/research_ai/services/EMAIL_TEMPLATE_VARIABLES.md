# Email template variables

Fixed email templates (e.g. RFP outreach) support **variable replacement** via placeholders in the form `{{entity.field}}`. This document lists all available entities and their properties.

**Usage:** Implemented in `email_template_variables.py`. Context is built by `build_replacement_context()` and applied with `replace_template_variables()`. Used in `email_generator_service.generate_expert_email()` when the API sends `template: null` and a `template_id` (fixed variable path).

---

## Syntax

- Placeholder format: `{{entity.field}}`
- Example: `Hi {{expert.name}}, we have a grant {{rfp.title}} that might interest you.`
- Unknown `entity.field` pairs are replaced with an empty string.

---

## Entities and properties

### `user`

The requesting user (sender). Built from the User model (and related `author_profile`, `organization`).


| Property       | Description                   |
| -------------- | ----------------------------- |
| `email`        | User's email address          |
| `full_name`    | `first_name` + `last_name`    |
| `first_name`   | User's first name             |
| `last_name`    | User's last name              |
| `headline`     | From user's author profile    |
| `organization` | From user's organization name |


**Example:** `{{user.full_name}}`, `{{user.email}}`

---

### `expert`

The expert resolved from the search. Built from the `resolved_expert` dict passed into `build_replacement_context()` (e.g. from `resolve_expert_from_search()`).


| Property      | Description                |
| ------------- | -------------------------- |
| `name`        | Salutation-style name: honorific + first + middle + last (from structured fields when present; else fallback to stored display `name`). Omits credentials suffix. |
| `title`       | Academic / job title (`academic_title` from search results) |
| `affiliation` | Institution or affiliation |
| `email`       | Expert's email address     |
| `expertise`   | Area(s) of expertise       |


**Example:** `{{expert.name}}`, `{{expert.affiliation}}`

---

### `rfp`

Grant/RFP context. Built from `build_rfp_context(grant)` in `rfp_email_context.py`.


| Property   | Description                             |
| ---------- | --------------------------------------- |
| `title`    | Grant title                             |
| `deadline` | Formatted deadline (e.g. from end_date) |
| `blurb`    | Short description of the grant          |
| `amount`   | Formatted amount (e.g. $5K, $200K)      |
| `url`      | Frontend URL to the grant page          |


**Example:** `{{rfp.title}}`, `{{rfp.deadline}}`, `{{rfp.url}}`

---

### `proposal`

Proposal (preregistration post) context. Built from `build_proposal_context(post_or_unified_document)` in `proposal_email_context.py`. Use when sending emails about a specific preregistration/proposal.


| Property             | Description                                      |
| -------------------- | ------------------------------------------------ |
| `title`              | Proposal title                                   |
| `url`                | Frontend URL to the proposal (preregistration)   |
| `created_by_name`    | Full name (or email) of the proposal creator    |
| `goal_amount`        | Funding goal, if linked to a fundraise (e.g. $5K) |
| `amount_raised`      | Amount raised so far (e.g. $1.2K)                |
| `contributor_count`  | Number of contributors                           |
| `deadline`           | Fundraise deadline, if any (e.g. March 17, 2026) |
| `blurb`              | Short snippet of the proposal body               |


**Example:** `{{proposal.title}}`, `{{proposal.url}}`, `{{proposal.created_by_name}}`, `{{proposal.amount_raised}}`

---

## Extending

To add a new variable:

1. Add the key to the appropriate tuple in `email_template_variables.py` (`USER_VARIABLES`, `RFP_VARIABLES`, `PROPOSAL_VARIABLES`, or `EXPERT_VARIABLES`).
2. Update the corresponding `_build_*_context()` function to include the new field.
3. Update this README.

