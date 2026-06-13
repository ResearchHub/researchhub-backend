"""Tests for research_ai.tasks: expert search, bulk email, send queued emails."""

from unittest.mock import patch

from django.test import TestCase, override_settings

from research_ai.models import Expert, ExpertSearch, GeneratedEmail
from research_ai.tasks import (
    _update_search_progress,
    process_bulk_generate_emails_task,
    run_expert_finder_search,
    send_queued_emails_task,
)
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


# --- run_expert_finder_search (Celery) ---


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RunExpertFinderSearchTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("task_user")
        self.search = ExpertSearch.objects.create(
            created_by=self.user,
            query="Task query",
            status=ExpertSearch.Status.PENDING,
            excluded_search_ids=[42],
        )

    @patch("research_ai.tasks.expert_finder_service_mod.run_expert_finder_search")
    def test_task_merges_excluded_search_ids_from_model_when_kwargs_omitted(
        self, mock_run
    ):
        mock_run.return_value = {
            "status": ExpertSearch.Status.COMPLETED,
            "experts": [],
            "expert_count": 1,
            "report_urls": {"pdf": "/p", "csv": "/c"},
            "llm_model": "m",
        }
        run_expert_finder_search.apply(
            kwargs={
                "search_id": str(self.search.id),
                "query": self.search.query,
                "config": {},
            }
        ).get()
        mock_run.assert_called_once()
        kw = mock_run.call_args.kwargs
        self.assertEqual(kw["excluded_search_ids"], [42])


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

    @patch("research_ai.tasks.sentry")
    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_one_fails_marks_failed_and_logs_sentry(
        self, mock_generate, mock_sentry
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
        mock_sentry.log_error.assert_called_once()

    @patch("research_ai.tasks.sentry")
    @patch("research_ai.tasks.generate_expert_email")
    def test_process_bulk_outer_exception_marks_all_failed_and_logs_sentry(
        self, mock_generate, mock_sentry
    ):
        """
        Top-level exception (e.g. User.objects.get raises) marks all ids FAILED
        and logs to Sentry.
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
        with patch(
            "research_ai.tasks.User.objects.get", side_effect=RuntimeError("DB error")
        ):
            with self.assertRaises(RuntimeError):
                process_bulk_generate_emails_task.apply(
                    kwargs={
                        "generated_email_ids": [rec.id],
                        "template_id": 1,
                        "created_by_id": self.user.id,
                    }
                ).get()
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.FAILED)
        mock_sentry.log_error.assert_called_once()


# --- send_queued_emails_task ---


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SendQueuedEmailsTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("send_user")

    @patch("research_ai.tasks.send_plain_email")
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
                "from_email": None,
            }
        ).get()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.SEND_FAILED)
        mock_send.assert_not_called()

    @patch("research_ai.tasks.send_plain_email")
    def test_send_queued_send_raises_marks_send_failed(self, mock_send):
        mock_send.side_effect = Exception("SMTP error")
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
                "from_email": None,
            }
        ).get()
        self.assertEqual(result["sent"], 0)
        self.assertEqual(result["failed"], 1)
        rec.refresh_from_db()
        self.assertEqual(rec.status, GeneratedEmail.Status.SEND_FAILED)

    @patch("research_ai.tasks.send_plain_email")
    def test_send_queued_success_sets_expert_last_email_sent_at(self, mock_send):
        mock_send.return_value = "ses-1"
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
                "from_email": None,
            }
        ).get()
        ex = Expert.objects.get(email__iexact="sentmark@edu")
        self.assertIsNotNone(ex.last_email_sent_at)
        if before:
            self.assertGreaterEqual(ex.last_email_sent_at, before)
