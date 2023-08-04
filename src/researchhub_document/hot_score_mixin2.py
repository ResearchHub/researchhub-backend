import datetime
import math

import numpy as np
from django.db.models import Count, Q

from discussion.models import Vote
from researchhub_document.models.constants.document_type import PAPER


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
        half_days_since_epoch = num_seconds_since_epoch / num_seconds_in_one_day
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
            social_media_score = math.log(doc.twitter_score + 1, 7)

        return social_media_score

    def calculate_hot_score_v2(self, should_save=False):
        hot_score = 0
        doc = self.get_document()

        total_comment_vote_score = self._count_doc_comment_votes(doc)
        boost_score = self._calc_boost_score()

        if self.document_type == PAPER:
            doc_vote_net_score = doc.calculate_score(ignore_twitter_score=True)
        else:
            doc_vote_net_score = doc.calculate_score()

        time_score = self._get_time_score(self.created_date)
        time_score_with_magnitude = self._c(doc_vote_net_score) * time_score
        social_media_score = self._calc_social_media_score()
        doc_vote_score = math.log(abs(doc_vote_net_score) + 1, 3)
        discussion_vote_score = math.log(max(0, total_comment_vote_score) + 1, 3)
        discussion_count_score = doc.discussion_count

        agg_score = (
            discussion_vote_score
            + doc_vote_score
            + discussion_count_score
            + social_media_score
            + boost_score
        )

        hot_score = agg_score + time_score_with_magnitude

        debug_obj = {
            "unified_doc_id": self.id,
            "inner_doc_id": doc.id,
            "document_type": self.document_type,
            "created_date": self.created_date,
            "discussion_count": {
                "count": doc.discussion_count,
                "=score": discussion_count_score,
            },
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
