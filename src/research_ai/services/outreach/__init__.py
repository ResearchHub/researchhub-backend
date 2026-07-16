"""Expert outreach: generating, templating, and sending emails to experts.

- ``email_generator`` -- LLM generation of outreach emails for an expert.
- ``email_sender`` -- SES send of a finished email.
- ``template_service`` -- CRUD/rendering of user-defined email templates.
- ``template_variables`` -- ``{{entity.field}}`` variable substitution (see
  ``EMAIL_TEMPLATE_VARIABLES.md`` in this directory).
- ``document_context`` -- resolves the search's document into email context.
- ``rfp_email_context`` / ``proposal_email_context`` -- RFP- and
  proposal-specific context builders on top of ``document_context``.
- ``rfp_invite`` -- invite flow for RFP outreach.
- ``invited_experts`` -- invited-expert listings, stats, and access grants.
- ``outreach_history`` -- per-expert outreach history rollups.
"""
