"""Expert outreach: generating, templating, and sending emails to experts.

- ``email_generator`` -- LLM generation of outreach emails for an expert.
- ``instantly_client`` -- Instantly API v2 HTTP client.
- ``mailbox_service`` -- connect/detach Gmail accounts and capacity checks.
- ``campaign_service`` -- publish campaigns and bulk-add Instantly leads.
- ``webhook_service`` -- Instantly status webhooks for sends and mailboxes.
- ``template_rewrite_service`` -- Bedrock rewrite of shared EmailTemplates.
- ``template_service`` -- CRUD/rendering of user-defined email templates.
- ``template_variables`` -- ``{{entity.field}}`` variable substitution (see
  ``EMAIL_TEMPLATE_VARIABLES.md`` in this directory).
- ``document_context`` -- resolves the search's document into email context.
- ``rfp_email_context`` / ``proposal_email_context`` -- RFP- and
  proposal-specific context builders on top of ``document_context``.
- ``rfp_invite`` -- invite flow for RFP outreach.
- ``proposal_draft_outreach`` -- bridges completed proposal drafts into
  outreach emails (invite links and prompt context).
- ``invited_experts`` -- invited-expert listings, stats, and access grants.
- ``outreach_history`` -- per-expert outreach history rollups.
"""
