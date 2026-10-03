"""Tests for research_ai.tasks: expert search, bulk email, send queued emails."""

from datetime import timedelta
from unittest.mock import ANY, MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import (
    AgentConversation,
    AgentExecution,
    AgentFile,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    ProposalDraft,
    SearchExpert,
)
from research_ai.services.outreach.gmail_sender import (
    GmailNeedsReauthError,
    OutreachSendResult,
)
from research_ai.services.usage_budget import ReservationHeartbeat
from research_ai.tasks import (
    _update_search_progress,
    process_agent_file_task,
    process_bulk_generate_emails_task,
    purge_agent_files,
    reclaim_lost_agent_runs,
    run_proposal_draft_task,
    send_queued_emails_task,
)
from research_ai.tests.agent_files.helpers import make_file, pdf_bytes
from researchhub.services.private_storage_service import PrivateStorageService
from user.tests.helpers import create_random_authenticated_user

# --- _update_search_progress ---


class UpdateSearchProgressTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("progress_user")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Progress test",
            status=ExpertSearch.Status.PENDING,
            progress=0,
        )

    def test_update_search_progress_updates_db(self):
        _update_search_progress(
            str(self.search.id),
            50,
            "Halfway there",
            status=ExpertSearch.Status.PROCESSING,
        )
        self.search.refresh_from_db()
        self.assertEqual(self.search.progress, 50)
        self.assertEqual(self.search.current_step, "Halfway there")
        self.assertEqual(self.search.status, ExpertSearch.Status.PROCESSING)

    def test_update_search_progress_truncates_long_message(self):
        _update_search_progress(str(self.search.id), 10, "x" * 600)
        self.search.refresh_from_db()
        self.assertEqual(len(self.search.current_step), 512)

    def test_update_search_progress_invalid_id_logs_and_does_not_raise(self):
        _update_search_progress("99999999", 0, "No-op")  # no such id – should not raise


# --- process_bulk_generate_emails_task ---


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ProcessBulkGenerateEmailsTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("bulk_user")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Bulk test",
            status=ExpertSearch.Status.COMPLETED,
        )

    def test_process_bulk_empty_ids_returns_processed_zero(self):
        result = process_bulk_generate_emails_task.apply(
            kwargs={
                "generated_email_ids": [],
                "template_id": None,
                "created_by_id": None,
            }
        ).get()
        self.assertEqual(result["processed"], 0)

    def test_process_bulk_no_processing_placeholders_returns_processed_zero(self):
        """
        When no records with status=PROCESSING exist for the given ids,
        task returns early.
        """
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. X",
            expert_email="x@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.DRAFT,  # not PROCESSING
        )
        result = process_bulk_generate_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "template_id": None,
                "created_by_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["processed"], 0)

    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_success_updates_records_to_draft(self, mock_generate):
        mock_generate.return_value = ("Subject line", "Body text")
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. X",
            expert_email="x@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.PROCESSING,
        )
        result = process_bulk_generate_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "template_id": None,
                "created_by_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 0)
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.DRAFT)
        self.assertEqual(rec.email_subject, "Subject line")
        self.assertEqual(rec.email_body, "Body text")

    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_fixed_stored_template_passes_null_llm_key(
        self, mock_generate
    ):
        mock_generate.return_value = ("Subj fixed", "Body fixed")
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. X",
            expert_email="x@example.com",
            template=None,
            status=GeneratedEmail.Status.PROCESSING,
        )
        result = process_bulk_generate_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "template_id": 99,
                "created_by_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["processed"], 1)
        kw = mock_generate.call_args[1]
        self.assertIsNone(kw["template"])
        self.assertEqual(kw["template_id"], 99)

    @patch("research_ai.tasks.logger")
    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_one_fails_marks_failed_and_logs(
        self, mock_generate, mock_logger
    ):
        rec_ok = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. A",
            expert_email="a@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.PROCESSING,
        )
        rec_fail = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. B",
            expert_email="b@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.PROCESSING,
        )

        def side_effect(*args, **kwargs):
            if kwargs.get("resolved_expert", {}).get("email") == "b@example.com":
                raise ValueError("Generation failed")
            return ("Subj", "Body")

        mock_generate.side_effect = side_effect
        result = process_bulk_generate_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec_ok.id, rec_fail.id],
                "template_id": None,
                "created_by_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 1)
        rec_ok.refresh_from_db()
        rec_fail.refresh_from_db()
        self.assertEqual(rec_ok.status, GeneratedEmail.Status.DRAFT)
        self.assertEqual(rec_fail.status, GeneratedEmail.Status.FAILED)
        mock_logger.warning.assert_called_once()

    @patch("research_ai.tasks.logger")
    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_outer_exception_marks_all_failed_and_logs(
        self, mock_generate, mock_logger
    ):
        """
        Top-level exception (e.g. User.objects.get raises) marks all ids FAILED
        and logs the error.
        """
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_search=self.expert_search,
            expert_name="Dr. X",
            expert_email="x@example.com",
            template="collaboration",
            status=GeneratedEmail.Status.PROCESSING,
        )
        mock_generate.return_value = ("Subj", "Body")
        with (
            patch(
                "research_ai.tasks.User.objects.get",
                side_effect=RuntimeError("DB error"),
            ),
            self.assertRaises(RuntimeError),
        ):
            process_bulk_generate_emails_task.apply(
                kwargs={
                    "generated_email_ids": [rec.id],
                    "template_id": 1,
                    "created_by_id": self.user.id,
                }
            ).get()
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.FAILED)
        mock_logger.exception.assert_called_once()


# --- send_queued_emails_task ---


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    OUTREACH_SEND_MIN_INTERVAL_SECONDS=0,
)
class SendQueuedEmailsTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("send_user")

    @patch("research_ai.tasks.send_outreach_email")
    def test_send_queued_empty_expert_email_marks_send_failed(self, mock_send):
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="No Email",
            expert_email="",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )
        result = send_queued_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "reply_to": None,
                "cc": None,
                "sender_user_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["deferred"], 0)
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.SEND_FAILED)
        mock_send.assert_not_called()

    @patch("research_ai.tasks.send_outreach_email")
    def test_send_queued_send_raises_marks_send_failed(self, mock_send):
        mock_send.side_effect = Exception("Gmail API error")
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="Dr. Y",
            expert_email="y@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )
        result = send_queued_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "reply_to": None,
                "cc": None,
                "sender_user_id": self.user.id,
            }
        ).get()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["deferred"], 0)
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.SEND_FAILED)

    @patch("research_ai.tasks.send_outreach_email")
    def test_needs_reauth_fails_remaining_queued_rows(
        self, mock_send: MagicMock
    ) -> None:
        """On Gmail needs_reauth, fail the current row and abort the rest of the batch."""
        # Arrange
        mock_send.side_effect = [
            OutreachSendResult(message_id="ok-1", open_tracking_token="t1"),
            GmailNeedsReauthError(),
            OutreachSendResult(message_id="should-not-send"),
        ]
        experts = [
            Expert.objects.create(email=email)
            for email in (
                "first@example.com",
                "second@example.com",
                "third@example.com",
            )
        ]
        records = [
            GeneratedEmail.objects.create(
                created_by=self.user,
                expert_email=expert.email,
                email_subject="Subject",
                email_body="Body",
                status=GeneratedEmail.Status.SENDING,
            )
            for expert in experts
        ]

        # Act
        with patch("research_ai.tasks.grant_invited_expert_access_for_send") as grant:
            result = send_queued_emails_task.apply(
                kwargs={
                    "generated_email_ids": [record.id for record in records],
                    "sender_user_id": self.user.id,
                }
            ).get()
        for record in [*records, *experts]:
            record.refresh_from_db()

        # Assert
        self.assertEqual(result, {"sent": 1, "failed": 2, "deferred": 0})
        self.assertEqual(records[0].status, GeneratedEmail.Status.SENT)
        self.assertEqual(records[0].gmail_message_id, "ok-1")
        self.assertEqual(records[1].status, GeneratedEmail.Status.SEND_FAILED)
        self.assertEqual(records[2].status, GeneratedEmail.Status.SEND_FAILED)
        self.assertEqual(mock_send.call_count, 2)
        grant.assert_called_once_with(generated_email=records[0])

    @patch("research_ai.tasks.send_outreach_email")
    def test_send_queued_success_sets_expert_last_email_sent_at(self, mock_send):
        mock_send.return_value = OutreachSendResult(
            message_id="gmail-1",
            thread_id="thr-1",
            open_tracking_token="tok-1",
        )
        Expert.objects.create(
            email="sentmark@edu",
            first_name="S",
            last_name="ent",
        )
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="Dr. S",
            expert_email="sentmark@edu",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )
        before = Expert.objects.get(email__iexact="sentmark@edu").last_email_sent_at
        send_queued_emails_task.apply(
            kwargs={
                "generated_email_ids": [rec.id],
                "reply_to": None,
                "cc": None,
                "sender_user_id": self.user.id,
            }
        ).get()
        rec.refresh_from_db()
        self.assertEqual(rec.channels, [GeneratedEmail.Channel.EMAIL])
        self.assertEqual(rec.gmail_message_id, "gmail-1")
        ex = Expert.objects.get(email__iexact="sentmark@edu")
        self.assertIsNotNone(ex.last_email_sent_at)
        if before:
            self.assertGreaterEqual(ex.last_email_sent_at, before)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    OUTREACH_SEND_MIN_INTERVAL_SECONDS=1200,
    OUTREACH_SEND_MAX_INTERVAL_SECONDS=1800,
)
class SendQueuedEmailsPacingTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("pace_user")

    def _sending(self, email: str) -> GeneratedEmail:
        return GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="Expert",
            expert_email=email,
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )

    @patch("research_ai.tasks.send_queued_emails_task.apply_async")
    @patch("research_ai.tasks.send_outreach_email")
    def test_bulk_requeues_remaining_with_random_countdown(
        self, mock_send, mock_apply_async
    ):
        # Arrange
        mock_send.return_value = OutreachSendResult(message_id="gmail-1")
        first = self._sending("a@example.com")
        second = self._sending("b@example.com")
        third = self._sending("c@example.com")

        # Act
        with patch("research_ai.tasks.grant_invited_expert_access_for_send"):
            result = send_queued_emails_task.apply(
                kwargs={
                    "generated_email_ids": [first.id, second.id, third.id],
                    "reply_to": ["reply@example.com"],
                    "cc": ["cc@example.com"],
                    "sender_user_id": self.user.id,
                    "immediate": False,
                }
            ).get()

        # Assert — one sent now; rest stay SENDING and are re-queued
        self.assertEqual(result, {"sent": 1, "failed": 0, "deferred": 2})
        first.refresh_from_db()
        second.refresh_from_db()
        third.refresh_from_db()
        self.assertEqual(first.status, GeneratedEmail.Status.SENT)
        self.assertEqual(second.status, GeneratedEmail.Status.SENDING)
        self.assertEqual(third.status, GeneratedEmail.Status.SENDING)
        self.assertEqual(mock_send.call_count, 1)
        mock_apply_async.assert_called_once()
        call_kwargs = mock_apply_async.call_args.kwargs
        self.assertEqual(
            call_kwargs["kwargs"]["generated_email_ids"],
            [second.id, third.id],
        )
        self.assertEqual(call_kwargs["kwargs"]["reply_to"], ["reply@example.com"])
        self.assertEqual(call_kwargs["kwargs"]["cc"], ["cc@example.com"])
        self.assertEqual(call_kwargs["kwargs"]["sender_user_id"], self.user.id)
        self.assertFalse(call_kwargs["kwargs"]["immediate"])
        self.assertGreaterEqual(call_kwargs["countdown"], 1200)
        self.assertLessEqual(call_kwargs["countdown"], 1800)

    @patch("research_ai.tasks.send_queued_emails_task.apply_async")
    @patch("research_ai.tasks.send_outreach_email")
    def test_immediate_sends_without_pacing(self, mock_send, mock_apply_async):
        # Arrange — prior send exists; single/immediate still sends now
        mock_send.return_value = OutreachSendResult(message_id="gmail-now")
        prior = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_name="Prior",
            expert_email="prior@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENT,
        )
        GeneratedEmail.objects.filter(id=prior.id).update(
            updated_date=timezone.now() - timedelta(seconds=60)
        )
        queued = self._sending("next@example.com")

        # Act
        with patch("research_ai.tasks.grant_invited_expert_access_for_send"):
            result = send_queued_emails_task.apply(
                kwargs={
                    "generated_email_ids": [queued.id],
                    "sender_user_id": self.user.id,
                    "immediate": True,
                }
            ).get()

        # Assert
        self.assertEqual(result, {"sent": 1, "failed": 0, "deferred": 0})
        queued.refresh_from_db()
        self.assertEqual(queued.status, GeneratedEmail.Status.SENT)
        mock_send.assert_called_once()
        mock_apply_async.assert_not_called()


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RunProposalDraftTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("draft_user")
        self.expert = Expert.objects.create(email="draft-expert@example.edu")
        self.expert_search = ExpertSearch.objects.create(
            created_by=self.user,
            query="protein folding",
        )
        self.search_expert = SearchExpert.objects.create(
            expert_search=self.expert_search,
            expert=self.expert,
        )
        self.draft = ProposalDraft.objects.create(
            search_expert=self.search_expert,
            created_by=self.user,
        )

    @patch("research_ai.tasks.run_proposal_draft")
    def test_runs_service(self, mock_run):
        # Arrange
        mock_run.return_value = {
            "status": ProposalDraft.Status.COMPLETED,
            "proposal_draft_id": self.draft.id,
        }

        # Act
        result = run_proposal_draft_task.apply(args=[self.draft.id]).get()

        # Assert
        mock_run.assert_called_once_with(
            self.search_expert.id, draft_id=self.draft.id, model_ref=None, heartbeat=ANY
        )
        self.assertEqual(result["status"], ProposalDraft.Status.COMPLETED)
        self.draft.refresh_from_db()
        self.assertIsNotNone(self.draft.processing_time)

    @patch("research_ai.tasks.run_proposal_draft")
    def test_runs_the_draft_under_a_heartbeat_on_its_lease(self, mock_run):
        # Arrange: the claim sets the lease the heartbeat renews.
        mock_run.return_value = {"status": ProposalDraft.Status.COMPLETED}

        # Act
        run_proposal_draft_task.apply(args=[self.draft.id]).get()

        # Assert
        heartbeat = mock_run.call_args.kwargs["heartbeat"]
        self.assertIsInstance(heartbeat, ReservationHeartbeat)
        self.assertEqual([target.id for target in heartbeat.targets], [self.draft.id])

    @patch("research_ai.tasks.run_proposal_draft")
    def test_forwards_the_drafts_selected_model(self, mock_run):
        # Arrange
        self.draft.model_ref = "claude_platform:claude-sonnet-5"
        self.draft.save(update_fields=["model_ref"])
        mock_run.return_value = {
            "status": ProposalDraft.Status.COMPLETED,
            "proposal_draft_id": self.draft.id,
        }

        # Act
        run_proposal_draft_task.apply(args=[self.draft.id]).get()

        # Assert
        mock_run.assert_called_once_with(
            self.search_expert.id,
            draft_id=self.draft.id,
            model_ref="claude_platform:claude-sonnet-5",
            heartbeat=ANY,
        )

    @patch("research_ai.tasks.run_proposal_draft")
    def test_forwards_the_drafts_generation_options(self, mock_run):
        # Arrange
        self.draft.run_config = {
            "effort": "high",
            "thinking": "disabled",
            "temperature": 0.4,
        }
        self.draft.save(update_fields=["run_config"])
        mock_run.return_value = {
            "status": ProposalDraft.Status.COMPLETED,
            "proposal_draft_id": self.draft.id,
        }

        # Act
        run_proposal_draft_task.apply(args=[self.draft.id]).get()

        # Assert
        mock_run.assert_called_once_with(
            self.search_expert.id,
            draft_id=self.draft.id,
            model_ref=None,
            heartbeat=ANY,
            effort="high",
            thinking="disabled",
            temperature=0.4,
        )

    @patch("research_ai.tasks.run_proposal_draft")
    def test_unexpected_error_marks_draft_failed(self, mock_run):
        # Arrange
        mock_run.side_effect = SearchExpert.DoesNotExist("SearchExpert gone")

        # Act & Assert
        with self.assertRaises(SearchExpert.DoesNotExist):
            run_proposal_draft_task.apply(args=[self.draft.id]).get()
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, ProposalDraft.Status.FAILED)
        self.assertIn("SearchExpert gone", self.draft.error_message)

    def test_missing_draft_returns_not_found(self):
        # Act
        result = run_proposal_draft_task.apply(args=[999999]).get()

        # Assert
        self.assertEqual(result, {"status": "not_found", "draft_id": 999999})

    @patch("research_ai.tasks.run_proposal_draft")
    def test_already_claimed_draft_is_not_run_twice(self, mock_run):
        # Arrange
        self.draft.status = ProposalDraft.Status.PROCESSING
        self.draft.save(update_fields=["status"])

        # Act
        result = run_proposal_draft_task.apply(args=[self.draft.id]).get()

        # Assert
        mock_run.assert_not_called()
        self.assertEqual(result["status"], ProposalDraft.Status.PROCESSING)
        self.assertEqual(result["skipped"], "already_claimed")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ReclaimLostAgentRunsTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("reclaim_user")
        self.lapsed = timezone.now() - timedelta(seconds=1)

    def test_fails_turns_and_drafts_whose_worker_stopped_heartbeating(self):
        # Arrange
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        execution = AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.RUNNING,
            attempt=1,
            usage_reservation_expires_at=self.lapsed,
        )
        expert = Expert.objects.create(email="reclaim-expert@example.edu")
        search_expert = SearchExpert.objects.create(
            expert_search=ExpertSearch.objects.create(
                created_by=self.user, query="protein folding"
            ),
            expert=expert,
        )
        draft = ProposalDraft.objects.create(
            search_expert=search_expert,
            created_by=self.user,
            status=ProposalDraft.Status.PROCESSING,
            usage_reservation_expires_at=self.lapsed,
        )

        # Act
        result = reclaim_lost_agent_runs.apply().get()

        # Assert
        self.assertEqual(
            result, {"executions": [execution.id], "proposal_drafts": [draft.id]}
        )
        execution.refresh_from_db()
        draft.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.FAILED)
        self.assertEqual(execution.stop_reason, "worker_lost")
        self.assertEqual(draft.status, ProposalDraft.Status.FAILED)

    def test_leaves_live_work_alone(self):
        # Arrange
        conversation = AgentConversation.objects.create(
            user=self.user, workflow="notebook_chat"
        )
        execution = AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.RUNNING,
            attempt=1,
            usage_reservation_expires_at=timezone.now() + timedelta(minutes=1),
        )

        # Act
        result = reclaim_lost_agent_runs.apply().get()

        # Assert
        self.assertEqual(result, {"executions": [], "proposal_drafts": []})
        execution.refresh_from_db()
        self.assertEqual(execution.status, AgentExecution.Status.RUNNING)


class AgentFileTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("file_task_user")

    @patch.object(PrivateStorageService, "read", return_value=pdf_bytes("Aims"))
    def test_process_task_extracts_the_uploaded_file(self, _mock_read):
        # Arrange
        file = make_file(self.user, status=AgentFile.Status.PROCESSING, text="")

        # Act
        result = process_agent_file_task.apply(args=[file.id]).get()

        # Assert
        self.assertEqual(result, {"file_id": file.id, "status": "READY"})
        file.refresh_from_db()
        self.assertEqual(file.text, "[Page 1]\nAims")

    @patch.object(PrivateStorageService, "delete")
    def test_purge_task_removes_abandoned_uploads(self, mock_delete):
        # Arrange
        file = make_file(self.user)
        AgentFile.objects.filter(id=file.id).update(
            created_date=timezone.now() - timedelta(days=2)
        )

        # Act
        result = purge_agent_files.apply().get()

        # Assert
        self.assertEqual(result, {"purged": 1})
        self.assertFalse(AgentFile.objects.filter(id=file.id).exists())
        mock_delete.assert_called_once_with(file.storage_key)
