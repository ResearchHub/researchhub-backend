import datetime
import math
from researchhub_document.related_models.constants.document_type import PAPER
import numpy as np
from django.db.models import (
    Q,
    Count
)
from discussion.models import Vote


class HotScoreMixin:

    def _c(self, num):
        if num >= 0:
            return 1
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

    # Returns a value between 0 and 1
    # The further away the given date is from now, the smaller the value
    def _get_date_val(self, date):
        input_date = date.replace(tzinfo=None)
        now = datetime.datetime.now()

        epoch_date = datetime.datetime(2020, 1, 1)
        days_since_epoch = (now - epoch_date).days
        mins_since_epoch = days_since_epoch * 24 * 60
        delta_dt = now - input_date
        days_elapsed_since_input_date = delta_dt.days + delta_dt.seconds / 60 / 60 / 24
        mins_elapsed_since_input_date = days_elapsed_since_input_date * 60 * 24

        time_penalty = 0
        if (days_elapsed_since_input_date > 1 and days_elapsed_since_input_date <= 5):
            time_penalty = 0.25
        elif (days_elapsed_since_input_date > 5 and days_elapsed_since_input_date <= 10):
            time_penalty = 0.35
        elif (days_elapsed_since_input_date > 10 and days_elapsed_since_input_date <= 25):
            time_penalty = 0.5
        elif (days_elapsed_since_input_date > 25):
            time_penalty = 0.75

        val = (mins_since_epoch - mins_elapsed_since_input_date) / mins_since_epoch
        final_val = np.power(val - (val * time_penalty), 2)
        # Ensure no negative values. This can happen if date is in future
        final_val = max(0, final_val)

        # Debug
        if False:
            print(f'Value for {date} is: {final_val}')

        return final_val

    def _calc_boost_score(self):
        boost_score = 0
        try:
            doc = self.get_document()
            boost = doc.get_boost_amount()
            date_val = self._get_date_val(self.created_date)
            boost_score = date_val * math.log(boost + 1, 5)
        except Exception as e:
            print(e)

        return boost_score

    def _calc_social_media_score(self):
        social_media_score = 0
        doc = self.get_document()

        date_val = self._get_date_val(self.created_date)
        if self.document_type == PAPER:
            twitter_score = math.log(doc.twitter_score+1, 7)
            social_media_score = date_val * twitter_score

        return social_media_score

    def calculate_hot_score_v2(self, should_save=False):
        hot_score = 0
        doc = self.get_document()

        total_comment_vote_score = self._count_doc_comment_votes(doc)
        boost_score = self._calc_boost_score()
        time_score = self._get_date_val(self.created_date)

        if self.document_type == PAPER:
            doc_vote_net_score = doc.calculate_score(ignore_twitter_score=True)
        else:
            doc_vote_net_score = doc.calculate_score()

        social_media_score = self._calc_social_media_score()
        doc_vote_score = self._c(doc_vote_net_score) * math.log(abs(doc_vote_net_score) + 1, 3)
        discussion_vote_score = math.log(max(0, total_comment_vote_score) + 1, 3)
        discussion_count_score = math.log(doc.discussion_count + 1, 2)

        agg_score = (
            discussion_vote_score + 
            doc_vote_score +
            discussion_count_score +
            social_media_score +
            boost_score
        )

        hot_score = (agg_score * time_score) * 10000

        debug_obj = {
            'unified_doc_id': self.id,
            'inner_doc_id': doc.id,
            'document_type': self.document_type,
            'created_date': self.created_date,
            'discussion_count': {
                'count': doc.discussion_count,
                '=score': discussion_count_score 
            },
            'discussion_votes': {
                'total_comment_vote_score': total_comment_vote_score,
                '=score': discussion_vote_score 
            },            
            'votes': {
                'doc_votes': doc_vote_net_score,
                '=score': doc_vote_score
            },
            'social_media': {
                '=score': social_media_score
            },
            'boost_score': {
                '=score': boost_score
            },
            'agg_score': agg_score,
            'time_score': time_score,
            '=hot_score': hot_score,
        }

        if should_save:
            self.hot_score_v2 = hot_score
            self.save()

        return (hot_score, debug_obj)
