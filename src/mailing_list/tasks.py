from mailing_list.lib import base_email_context


def build_notification_context(actions):
    context = {**base_email_context}
    if isinstance(actions, (list, tuple)):
        context["actions"] = [act.email_context() for act in actions]
    else:
        context["action"] = actions.email_context()
    return context
