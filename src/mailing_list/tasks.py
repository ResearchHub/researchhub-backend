from discussion.lib import check_comment_in_threads, check_reply_in_threads
from discussion.models import Comment, Reply, Thread
from researchhub.celery import app
from user.tasks import get_latest_actions


def send_action_notification_emails(recipients):
    for recipient in recipients:
        if recipient.user is None:
            # TODO: get non-user actions
            pass
        else:
            actions, next_cursor = get_subscribed_actions(
                recipient.user,
                recipient.next_cursor,
                recipient.thread_subscription
            )
        send_email.delay(recipient, actions, next_cursor)


def get_subscribed_actions(user, action_cursor, thread_subscription):
    # TODO: Refactor
    # TODO: Store next cursor in db
    actions, next_cursor = get_latest_actions(action_cursor)
    user_threads = Thread.objects.filter(created_by=user)
    subscribed_actions = []

    for action in actions:
        item = action.item

        if isinstance(item, Comment):

            if thread_subscription.comments and not thread_subscription.none:
                if check_comment_in_threads(item, user_threads):
                    subscribed_actions.append(action)

        elif isinstance(item, Reply):

            if thread_subscription.replies and not thread_subscription.none:
                if check_reply_in_threads(item, user_threads):
                    subscribed_actions.append(action)

    return subscribed_actions, next_cursor


@app.task
def send_email(email_recipient, actions, next_cursor):
    pass
    # body = build_body(actions)
    # mail(email_recipient.email, body)
    # recipient.next_cursor = next_cursor
    # recipient.save()
