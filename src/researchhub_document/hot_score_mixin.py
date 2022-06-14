import datetime
import math

import numpy as np
from django.db.models import Count, Q

from discussion.models import Vote
from researchhub_document.related_models.constants.document_type import PAPER


class HotScoreMixin:
    def _c(self, num):
        if num > 0:
            return 1
        elif num == 0:
            return 0
        else:
            return -1

    def _count_doc_comment_votes(self, doc):
        vote_total = 0
        try:
            for t in doc.threads.filter(is_removed=False).iterator():
                vote_total += max(0, t.calculate_score())
                for c in t.comments.filter(is_removed=False).iterator():
                    vote_total += max(0, c.calculate_score())
                    for r in c.replies.filter(is_removed=False).iterator():
                        vote_total += max(0, r.calculate_score())
        except Exception as e:
            print(e)

        return vote_total

    def _get_time_score(self, date):
        num_seconds_in_half_day = 43000
        num_seconds_in_one_day = 86000

        input_date = date.replace(tzinfo=None)
        epoch_date = datetime.datetime(2020, 1, 1)

        num_seconds_since_epoch = (input_date - epoch_date).total_seconds()
        half_days_since_epoch = num_seconds_since_epoch / num_seconds_in_half_day
        time_score = half_days_since_epoch

        # Debug
        if False:
            print(f"Num seconds since epoch: {num_seconds_since_epoch}")
            print(f"Value for {date} is: {time_score}")

        return time_score

    def _calc_boost_score(self):
        boost_score = 0
        try:
            doc = self.get_document()
            boost = doc.get_boost_amount()
            boost_score = math.log(boost + 1, 10)
        except Exception as e:
            print(e)

        return boost_score

    def _calc_social_media_score(self):
        social_media_score = 0
        doc = self.get_document()

        if self.document_type == PAPER:
            social_media_score = math.log(doc.twitter_score + 1, 5)

        return social_media_score

    # The basic idea is to take a bunch of signals (e.g discussion count) and
    # add them to some time score elapsed since the epoch. The signals should be
    # somewhat comparable to the time score. To do that, we pass these signals through
    # log functions so that scores don't grow out of control.
    def calculate_hot_score_v2(self, should_save=False):
        MIN_REQ_DISCUSSIONS = 1
        hot_score = 0
        doc = self.get_document()

        if doc is None:
            return (0, 0)

        doc_vote_net_score = doc.calculate_score()

        total_comment_vote_score = self._count_doc_comment_votes(doc)
        boost_score = self._calc_boost_score()
        social_media_score = self._calc_social_media_score()
        time_score = self._get_time_score(self.created_date)
        time_score_with_magnitude = (
            self._c(doc_vote_net_score + social_media_score) * time_score
        )
        doc_vote_score = math.log(abs(doc_vote_net_score) + 1, 2)
        discussion_vote_score = math.log(doc.discussion_count + 1, 2) + math.log(
            max(0, total_comment_vote_score) + 1, 3
        )

        # If basic criteria needed to show in trending is not available,
        # penalize the score by subtracting time. This will result in the
        # document being sent to the back of the feed
        if doc.discussion_count == MIN_REQ_DISCUSSIONS:
            discussion_vote_score -= 2  # Roughly one day penalty
        elif (
            doc.discussion_count < MIN_REQ_DISCUSSIONS
            and time_score_with_magnitude >= 0
        ):
            time_score_with_magnitude *= -1

        agg_score = discussion_vote_score + doc_vote_score + boost_score

        hot_score = (agg_score + time_score_with_magnitude) * 1000

        debug_obj = {
            "unified_doc_id": self.id,
            "inner_doc_id": doc.id,
            "document_type": self.document_type,
            "created_date": self.created_date,
            "discussion_votes": {
                "total_comment_vote_score": total_comment_vote_score,
                "=score": discussion_vote_score,
            },
            "votes": {"doc_votes": doc_vote_net_score, "=score": doc_vote_score},
            "social_media": {"=score": social_media_score},
            "boost_score": {"=score": boost_score},
            "agg_score": agg_score,
            "time_score": time_score,
            "time_score_with_magnitude": time_score_with_magnitude,
            "=hot_score": hot_score,
        }

        if should_save:
            self.hot_score_v2 = hot_score
            self.save()

        return (hot_score, debug_obj)
