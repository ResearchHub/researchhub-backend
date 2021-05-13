import base64
import json
import time
import uuid


def decode_validation_token(encoded_str):
    return base64.urlsafe_b64decode(encoded_str).decode("ascii")


def encode_validation_token(str):
    return base64.urlsafe_b64encode(str.encode("ascii"))


def get_formatted_token(generated_time):
    return json.dumps({
        "generated_time": generated_time,
        "token": uuid.uuid4().hex,
    })


def get_new_validation_token():
    generated_time = int(time.time())
    token = encode_validation_token(get_formatted_token(generated_time))
    return [
        generated_time,
        token
    ]


# TODO: calvinhlee - write email sender here
def send_validation_email(case):
    return True
    # validation_token = case.validation_token
    # provided_email = case.provided_email 

    # users = Hub.objects.filter(
    #     subscribers__isnull=False,
    #     is_removed=False,
    # ).values_list('subscribers', flat=True)

    # # TODO find best by hub and then in mem sort for each user? more efficient?
    # emails = []
    # for user in User.objects.filter(id__in=users, is_suspended=False):
    #     if not check_can_receive_digest(user, frequency):
    #         continue
    #     users_papers = Paper.objects.filter(
    #         hubs__in=user.subscribed_hubs.all()
    #     )
    #     most_voted_and_uploaded_in_interval = users_papers.filter(
    #         uploaded_date__gte=start_date,
    #         uploaded_date__lte=end_date
    #     ).filter(score__gt=0).order_by('-score')[:3]
    #     most_discussed_in_interval = users_papers.annotate(
    #         discussions=thread_counts + comment_counts + reply_counts
    #     ).filter(discussions__gt=0).order_by('-discussions')[:3]
    #     most_voted_in_interval = users_papers.filter(score__gt=0).order_by('-score')[:2]
    #     papers = (
    #         most_voted_and_uploaded_in_interval
    #         or most_discussed_in_interval
    #         or most_voted_in_interval
    #     )
    #     if len(papers) == 0:
    #         continue

    #     email_context = {
    #         **base_email_context,
    #         'first_name': user.first_name,
    #         'last_name': user.last_name,
    #         'papers': papers,
    #         'preview_text': papers[0].tagline
    #     }

    #     recipient = [user.email]
    #     # subject = 'Research Hub | Your Weekly Digest'
    #     subject = papers[0].title[0:86] + '...'
    #     send_email_message(
    #         recipient,
    #         'weekly_digest_email.txt',
    #         subject,
    #         email_context,
    #         'weekly_digest_email.html',
    #         'ResearchHub Digest <digest@researchhub.com>'
    #     )
    #     emails += recipient

