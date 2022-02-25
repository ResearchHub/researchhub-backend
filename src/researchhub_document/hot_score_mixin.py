import datetime
import math

class HotScoreMixin:
    def _get_date_val(self, date):
        input_date = date.replace(tzinfo=None)
        now = datetime.datetime.now()

        # FIXME
        days_since_epoch = 730
        mins_since_epoch = days_since_epoch * 24 * 60
        delta_dt = now - input_date
        days_elapsed_since_input_date = delta_dt.days + delta_dt.seconds / 60 / 60 / 24
        mins_elapsed_since_input_date = days_elapsed_since_input_date * 60 * 24

        time_penalty = 0
        if (days_elapsed_since_input_date > 2 and days_elapsed_since_input_date <= 5):
            time_penalty = 0.25
        elif (days_elapsed_since_input_date > 5 and days_elapsed_since_input_date <= 10):
            time_penalty = 0.5
        elif (days_elapsed_since_input_date > 10 and days_elapsed_since_input_date <= 25):
            time_penalty = 0.6
        elif (days_elapsed_since_input_date > 25):
            time_penalty = 0.75

        val = (mins_since_epoch - mins_elapsed_since_input_date) / mins_since_epoch
        final_val = val - (val * time_penalty)

        # Debug
        if False:
            print(f'ID: {self.id}')
            print(f'Input date: {date}')
            print(f'Time Penalty: {time_penalty}')
            print(f'Days Elapsed: {days_elapsed_since_input_date}')
            print(f'Value: {final_val}')

        return final_val

    def _calc_social_media_score(self):
        # FIXME
        # social_media_score = math.log(self.twitter_score+1, 7)
        return 0

    def _calc_vote_score(self, votes):
        return sum([
            self._get_date_val(v.created_date) for v in votes
        ])

    def calculate_hot_score_v2(self, should_save=False):
        DISCUSSION_VOTE_WEIGHT = 2
        DOCUMENT_VOTE_WEIGHT = 1
        hot_score = 0
        doc = self.get_document()

        # Init debug
        debug_obj = {
            'unified_doc_id': self.id,
            'inner_doc_id': doc.id,
            'document_type': self.document_type,
        }

        # Doc vote score
        doc_vote_net_score = doc.calculate_score(ignore_twitter_score=True)
        doc_vote_time_score = self._calc_vote_score(doc.votes.all())
        doc_vote_score = doc_vote_net_score * doc_vote_time_score * DOCUMENT_VOTE_WEIGHT
        debug_obj['doc_vote_score'] = {'vote_net_score': doc_vote_net_score, 'vote_time_score': doc_vote_time_score, '=doc_vote_score': doc_vote_score}

        # Doc created date score
        doc_created_score = self._get_date_val(self.created_date)
        debug_obj['doc_created_score'] = {'created_date': self.created_date, '=doc_created_score': doc_created_score}

        # Doc social media score
        social_media_score = self._calc_social_media_score()
        debug_obj['social_media_score'] = {'=social_media_score': social_media_score}

        # Doc discussion vote score
        # Fixme: Ignore deleted
        discussion_vote_score = 0
        debug_obj['discussion_vote_score'] = {}
        for t in doc.threads.all():
            thread_vote_net_score = max(0, t.calculate_score())
            thread_vote_time_score = self._calc_vote_score(t.votes.all())
            thread_vote_score = thread_vote_net_score * thread_vote_time_score * DISCUSSION_VOTE_WEIGHT
            discussion_vote_score += thread_vote_score

            debug_val = {'vote_net_score': thread_vote_net_score, 'vote_time_score': thread_vote_time_score, '=thread_vote_score': thread_vote_score}
            debug_obj['discussion_vote_score'][f'thread (id:{t.id})'] = debug_val
            for c in t.comments.all():
                comment_vote_net_score = max(0, c.calculate_score())
                comment_vote_time_score = self._calc_vote_score(c.votes.all())
                comment_vote_score = comment_vote_net_score * comment_vote_time_score * DISCUSSION_VOTE_WEIGHT
                discussion_vote_score += comment_vote_score

                debug_val = {'vote_net_score': comment_vote_net_score, 'vote_time_score': comment_vote_time_score, '=comment_vote_score': comment_vote_score}
                debug_obj['discussion_vote_score'][f'thread (id:{t.id})'][f'comment (id:{c.id})'] = debug_val
                for r in c.replies.all():
                    reply_vote_net_score = max(0, r.calculate_score())
                    reply_vote_time_score = self._calc_vote_score(r.votes.all())
                    reply_vote_score = reply_vote_net_score * reply_vote_time_score * DISCUSSION_VOTE_WEIGHT
                    discussion_vote_score += reply_vote_score

                    debug_val = {'vote_net_score': reply_vote_net_score, 'vote_time_score': reply_vote_time_score, '=reply_vote_score': reply_vote_score}
                    debug_obj['discussion_vote_score'][f'thread (id:{t.id})'][f'comment (id:{c.id})'][f'reply (id:{r.id})'] = debug_val

        debug_obj['discussion_vote_score']['=discussion_vote_score'] = discussion_vote_score

        hot_score = (
            doc_created_score +
            doc_vote_score +
            discussion_vote_score +
            social_media_score
        ) * 10000
        debug_obj['=hot_score (x10000)'] = hot_score

        if should_save:
            self.hot_score_v2 = hot_score
            self.save()

        return (hot_score, debug_obj)
