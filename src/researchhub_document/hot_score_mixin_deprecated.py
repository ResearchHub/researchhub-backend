import datetime
import math

import numpy as np

from researchhub_document.related_models.constants.document_type import PAPER


class HotScoreMixinDEPRECATED:
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
        if days_elapsed_since_input_date > 1 and days_elapsed_since_input_date <= 5:
            time_penalty = 0.25
        elif days_elapsed_since_input_date > 5 and days_elapsed_since_input_date <= 10:
            time_penalty = 0.35
        elif days_elapsed_since_input_date > 10 and days_elapsed_since_input_date <= 25:
            time_penalty = 0.5
        elif days_elapsed_since_input_date > 25:
            time_penalty = 0.75

        val = (mins_since_epoch - mins_elapsed_since_input_date) / mins_since_epoch
        final_val = np.power(val - (val * time_penalty), 2)
        # Ensure no negative values. This can happen if date is in future
        final_val = max(0, final_val)

        # Debug
        if False:
            print(f"Value for {date} is: {final_val}")

        return final_val

    def _calc_social_media_score(self):
        social_media_score = 0
        doc = self.get_document()

        date_val = self._get_date_val(self.created_date)
        if self.document_type == PAPER:
            twitter_score = math.log(doc.twitter_score + 1, 2)
            social_media_score = date_val * twitter_score

        return social_media_score

    def _calc_boost_score(self):
        doc = self.get_document()
        boost = doc.get_boost_amount()
        date_val = self._get_date_val(self.created_date)
        boost_score = date_val * math.log(boost + 1, 2)

        return boost_score

    def _calc_vote_score(self, votes):
        return sum(
            map(self._get_date_val, votes.values_list("created_date", flat=True))
        )

    def _c(self, num):
        if num >= 1:
            return 1
        elif num == 0:
            return 0
        else:
            return -1

    # The basic idea is that the score of a document depends on the sum
    # of various interactions on it (i.e. votes). Each of which, depends
    # on how recent these interactions were. The more recent the interaction
    # is, the greater its value.
    # NOTE: use endpoint /api/researchhub_unified_document/{doc_id}/hot_score/?debug
    # to see a breakdown of how the hot score is calculated for a given document
    def calculate_hot_score_v2(self, should_save=False):
        DOCUMENT_VOTE_WEIGHT = 1
        DISCUSSION_VOTE_WEIGHT = 1
        DOCUMENT_CREATED_WEIGHT = 3
        hot_score = 0
        doc = self.get_document()

        # Init debug
        debug_obj = {
            "unified_doc_id": self.id,
            "inner_doc_id": doc.id,
            "document_type": self.document_type,
            "DISCUSSION_VOTE_WEIGHT": DISCUSSION_VOTE_WEIGHT,
            "DOCUMENT_VOTE_WEIGHT": DOCUMENT_VOTE_WEIGHT,
            "DOCUMENT_CREATED_WEIGHT": DOCUMENT_CREATED_WEIGHT,
        }

        # Doc vote score
        if self.document_type == PAPER:
            doc_vote_net_score = doc.calculate_score(ignore_twitter_score=True)
            votes = doc.votes.all()
        else:
            doc_vote_net_score = doc.calculate_score()
            votes = doc.votes.all()

        doc_vote_time_score = self._calc_vote_score(votes)
        doc_vote_score = (
            self._c(doc_vote_net_score) * doc_vote_time_score * DOCUMENT_VOTE_WEIGHT
        )
        debug_obj["doc_vote_score"] = {
            "vote_net_score": doc_vote_net_score,
            "vote_time_score": doc_vote_time_score,
            "=doc_vote_score (WEIGHTED)": doc_vote_score,
        }

        # Doc boost score
        boost_score = self._calc_boost_score()
        debug_obj["doc_boost_score"] = {"=doc_boost_score": boost_score}

        # Doc created date score
        doc_created_score = (
            self._get_date_val(self.created_date) * DOCUMENT_CREATED_WEIGHT
        )
        debug_obj["doc_created_score"] = {
            "created_date": self.created_date,
            "=doc_created_score (WEIGHTED)": doc_created_score,
        }

        # Doc social media score
        social_media_score = self._calc_social_media_score()
        debug_obj["social_media_score"] = {"=social_media_score": social_media_score}

        # Doc discussion vote score
        discussion_vote_score = 0
        debug_obj["discussion_vote_score"] = {}
        for thread in doc.threads.filter(is_removed=False).iterator():
            thread_vote_net_score = max(0, thread.calculate_score())
            thread_vote_time_score = self._calc_vote_score(thread.votes.all())
            thread_vote_score = (
                self._c(thread_vote_net_score)
                * thread_vote_time_score
                * DISCUSSION_VOTE_WEIGHT
            )
            discussion_vote_score += thread_vote_score

            debug_val = {
                "created_date": thread.created_date,
                "vote_net_score": thread_vote_net_score,
                "vote_time_score": thread_vote_time_score,
                "=thread_vote_score (WEIGHTED)": thread_vote_score,
            }
            debug_obj["discussion_vote_score"][f"thread (id:{thread.id})"] = debug_val
            for c in thread.comments.filter(is_removed=False).iterator():
                comment_vote_net_score = max(0, c.calculate_score())
                comment_vote_time_score = self._calc_vote_score(c.votes.all())
                comment_vote_score = (
                    self._c(comment_vote_net_score)
                    * comment_vote_time_score
                    * DISCUSSION_VOTE_WEIGHT
                )
                discussion_vote_score += comment_vote_score

                debug_val = {
                    "created_date": c.created_date,
                    "vote_net_score": comment_vote_net_score,
                    "vote_time_score": comment_vote_time_score,
                    "=comment_vote_score (WEIGHTED)": comment_vote_score,
                }
                debug_obj["discussion_vote_score"][f"thread (id:{t.id})"][
                    f"comment (id:{c.id})"
                ] = debug_val
                for r in c.replies.filter(is_removed=False).iterator():
                    reply_vote_net_score = max(0, r.calculate_score())
                    reply_vote_time_score = self._calc_vote_score(r.votes.all())
                    reply_vote_score = (
                        self._c(reply_vote_net_score)
                        * reply_vote_time_score
                        * DISCUSSION_VOTE_WEIGHT
                    )
                    discussion_vote_score += reply_vote_score

                    debug_val = {
                        "created_date": r.created_date,
                        "vote_net_score": reply_vote_net_score,
                        "vote_time_score": reply_vote_time_score,
                        "=reply_vote_score (WEIGHTED)": reply_vote_score,
                    }
                    debug_obj["discussion_vote_score"][f"thread (id:{t.id})"][
                        f"comment (id:{c.id})"
                    ][f"reply (id:{r.id})"] = debug_val

        debug_obj["discussion_vote_score"][
            "=discussion_vote_score"
        ] = discussion_vote_score

        hot_score = (
            doc_created_score
            + doc_vote_score
            + discussion_vote_score
            + social_media_score
            + boost_score
        )
        final_hot_score = hot_score * 10000
        debug_obj["hot_score"] = hot_score
        debug_obj["=hot_score (x10000)"] = final_hot_score

        if should_save:
            self.hot_score_v2 = final_hot_score
            self.save()

        return (final_hot_score, debug_obj)
