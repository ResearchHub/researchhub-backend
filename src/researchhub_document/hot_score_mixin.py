import datetime
import math

from django.db.models import Q

from purchase.related_models.constants.currency import RSC
from purchase.related_models.fundraise_model import Fundraise
from reputation.related_models.bounty import Bounty


class HotScoreMixin:
    def _c(self, num):
        if num > 0:
            return 1
        elif num == 0:
            return 0
        else:
            return -1

    def _count_doc_comment_votes(self, doc):
        return doc.rh_threads.filter(
            (Q(rh_comments__is_removed=False) & Q(rh_comments__parent__isnull=True))
            | (
                Q(rh_comments__parent__is_removed=False)
                & Q(rh_comments__parent__isnull=False)
            )
        ).count()

    def _get_relevant_date(self):
        """
        Get the most relevant date for the document.
        If a fundraise expires in the next 3 days, use that date.
        Otherwise, use the document creation date.
        """
        date = self.created_date

        # Define the 3-day threshold
        three_days = datetime.timedelta(days=3)
        now = datetime.datetime.now(datetime.timezone.utc)

        for fundraise in self.fundraises.all():
            # Only use end_date if it exists, is in the future,
            # within 3 days, and is greater than current date
            if (
                fundraise.end_date
                and fundraise.end_date > date
                and fundraise.end_date > now  # Check if end date hasn't passed
                and (fundraise.end_date - now) <= three_days
            ):
                date = fundraise.end_date

        return date

    def _get_time_score(self, date):
        num_seconds_in_half_day = 43000

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

    def _calc_bounty_score(self):
        total_bounty_score = 0

        try:
            bounty_promo_period = 259200
            open_bounties = Bounty.objects.filter(
                unified_document_id=self.id, status=Bounty.OPEN
            )

            for bounty in open_bounties:
                seconds_since_create = (
                    datetime.datetime.now(datetime.timezone.utc) - bounty.created_date
                ).total_seconds()
                seconds_to_expiration = (
                    bounty.expiration_date
                    - datetime.datetime.now(datetime.timezone.utc)
                ).total_seconds()
                percentage_within_promo_period = 0
                this_bounty_score = 0

                is_near_new = 0 < seconds_since_create < bounty_promo_period
                is_near_expire = 0 < seconds_to_expiration < bounty_promo_period

                if is_near_new:
                    percentage_within_promo_period = (
                        (bounty_promo_period - seconds_since_create)
                        / bounty_promo_period
                    ) * 100
                elif is_near_expire:
                    percentage_within_promo_period = (
                        (bounty_promo_period - seconds_to_expiration)
                        / bounty_promo_period
                    ) * 100

                if is_near_new or is_near_expire:
                    this_bounty_score = math.log(bounty.amount + 1, 100) + math.log(
                        percentage_within_promo_period + 1, 7
                    )
                    total_bounty_score += this_bounty_score

                # Useful for debugging, do not delete
                # print("bounty.created_date", bounty.created_date)
                # print("bounty.expiration_date", bounty.expiration_date)
                # print("seconds_since_create", seconds_since_create)
                # print("seconds_to_expiration", seconds_to_expiration)
                # print("id", bounty.id)
                # print("is_near_new", is_near_new)
                # print("is_near_expire", is_near_expire)
                # print("percentage_within_promo_period", percentage_within_promo_period)
                # print("score", this_bounty_score)

        except Exception as e:
            print(e)

        return total_bounty_score

    def _calc_fundraise_score(self):
        """
        Calculate score for fundraises similar to bounty score:
        - Higher scores for new fundraises or those close to expiring
        - Score based on amount raised and proximity to promotion period boundaries
        """
        total_fundraise_score = 0
        try:
            # Same promotion period as bounties (3 days in seconds)
            fundraise_promo_period = 259200
            # Get all open fundraises for this document
            fundraises = Fundraise.objects.filter(
                unified_document_id=self.id, status=Fundraise.OPEN
            )

            for fundraise in fundraises:
                # Get time since creation
                now = datetime.datetime.now(datetime.timezone.utc)
                seconds_since_create = (now - fundraise.start_date).total_seconds()

                # Calculate time to expiration if end_date exists
                seconds_to_expiration = 0
                if fundraise.end_date:
                    seconds_to_expiration = (fundraise.end_date - now).total_seconds()

                # Initialize variables
                percentage_within_promo_period = 0
                this_fundraise_score = 0

                # Check if fundraise is new or about to expire
                is_near_new = 0 < seconds_since_create < fundraise_promo_period
                is_near_expire = 0 < seconds_to_expiration < fundraise_promo_period

                # Calculate percentage within promotion period
                if is_near_new:
                    numerator = fundraise_promo_period - seconds_since_create
                    percentage_within_promo_period = (
                        numerator / fundraise_promo_period
                    ) * 100
                elif is_near_expire:
                    numerator = fundraise_promo_period - seconds_to_expiration
                    percentage_within_promo_period = (
                        numerator / fundraise_promo_period
                    ) * 100

                # Get amount raised in USD
                amount_raised = fundraise.get_amount_raised(currency=RSC)

                # Calculate score if in promotion period
                if is_near_new or is_near_expire:
                    # Use log base 100 for amount and log base 7 for percentage
                    amount_factor = math.log(amount_raised + 1, 100)
                    percent_factor = math.log(percentage_within_promo_period + 1, 7)
                    this_fundraise_score = amount_factor + percent_factor
                    total_fundraise_score += this_fundraise_score

        except Exception as e:
            print(e)

        return total_fundraise_score

    # The basic idea is to take a bunch of signals (e.g discussion count) and
    # add them to some time score elapsed since the epoch. The signals should be
    # somewhat comparable to the time score. To do that, we pass these signals through
    # log functions so that scores don't grow out of control.
    def calculate_hot_score(self, should_save=False):
        MIN_REQ_DISCUSSIONS = 1
        hot_score = 0
        doc = self.get_document()

        if doc is None:
            return (0, 0)

        doc_vote_net_score = doc.calculate_score()

        total_comment_vote_score = self._count_doc_comment_votes(doc)
        boost_score = self._calc_boost_score()
        bounty_score = self._calc_bounty_score()
        fundraise_score = self._calc_fundraise_score()

        relevant_date = self._get_relevant_date()
        time_score = self._get_time_score(relevant_date)

        time_score_with_magnitude = self._c(doc_vote_net_score) * time_score
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

        agg_score = (
            discussion_vote_score
            + doc_vote_score
            + boost_score
            + bounty_score
            + fundraise_score
        )

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
            "boost_score": {"=score": boost_score},
            "bounty_score": {"=score": bounty_score},
            "fundraise_score": {"=score": fundraise_score},
            "agg_score": agg_score,
            "time_score": time_score,
            "time_score_with_magnitude": time_score_with_magnitude,
            "=hot_score": hot_score,
        }

        if should_save:
            self.hot_score = hot_score
            self.save()

        return (hot_score, debug_obj)
