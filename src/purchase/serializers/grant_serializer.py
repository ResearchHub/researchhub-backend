from rest_framework import serializers

from ai_peer_review.serializers import serialize_ai_peer_review_summary
from purchase.models import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub.serializers import DynamicModelFieldSerializer
from user.serializers import DynamicAuthorSerializer, DynamicUserSerializer


class GrantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Grant
        fields = "__all__"
        read_only_fields = [
            "created_date",
            "updated_date",
            "start_date",
        ]


class DynamicGrantSerializer(DynamicModelFieldSerializer):
    created_by = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    post_id = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    applications = serializers.SerializerMethodField()

    class Meta:
        model = Grant
        fields = "__all__"

    def get_created_by(self, grant):
        context = self.context
        _context_fields = context.get("pch_dgs_get_created_by", {})
        serializer = DynamicUserSerializer(
            grant.created_by, context=context, **_context_fields
        )
        return serializer.data

    def get_contacts(self, grant):
        context = self.context
        _context_fields = context.get("pch_dgs_get_contacts", {})
        serializer = DynamicUserSerializer(
            grant.contacts.all(), context=context, many=True, **_context_fields
        )
        return serializer.data

    def get_post_id(self, grant):
        posts = grant.unified_document.posts.all()
        return posts[0].id if posts else None

    def get_amount(self, grant):
        """
        Return amount in multiple currencies for display flexibility
        """
        usd_amount = float(grant.amount)

        # Handle case where no exchange rate exists (e.g., in tests)
        try:
            rsc_amount = RscExchangeRate.usd_to_rsc(usd_amount)
        except AttributeError:
            # Fallback to None if no exchange rate is available
            rsc_amount = None

        return {
            "usd": usd_amount,
            "rsc": rsc_amount,
            "formatted": f"{grant.amount:,.2f} {grant.currency}",
        }

    def get_is_expired(self, grant):
        """
        Check if the grant application deadline has passed
        """
        return grant.is_expired()

    def get_is_active(self, grant):
        """
        Check if the grant is currently accepting applications
        """
        return grant.is_active()

    def get_applications(self, grant):
        """Return grant applications with applicant and fundraise information"""

        review_by_ud = {r.unified_document_id: r for r in grant.proposal_reviews.all()}
        application_data = []
        for application in grant.applications.all():
            if (
                application.applicant
                and hasattr(application.applicant, "author_profile")
                and application.applicant.author_profile
            ):
                applicant_data = DynamicAuthorSerializer(
                    application.applicant.author_profile
                ).data

                ai_rev = None
                if application.preregistration_post_id:
                    ud = application.preregistration_post.unified_document
                    ai_rev = review_by_ud.get(ud.id)
                entry = {
                    "id": application.id,
                    "created_date": application.created_date,
                    "applicant": applicant_data,
                    "preregistration_post_id": (
                        application.preregistration_post.id
                        if application.preregistration_post
                        else None
                    ),
                    "fundraise": self._serialize_application_fundraise(application),
                    "ai_peer_review": serialize_ai_peer_review_summary(ai_rev),
                }
                application_data.append(entry)

        return application_data

    @classmethod
    def _serialize_application_fundraise(cls, application):
        post = application.preregistration_post
        if (
            not post
            or not hasattr(post, "unified_document")
            or not post.unified_document
        ):
            return None

        ud = post.unified_document
        if not hasattr(ud, "fundraises"):
            return None

        fundraises = ud.fundraises.all()
        if not fundraises:
            return None
        fundraise = fundraises[0]

        usd_goal = float(fundraise.goal_amount)
        try:
            rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
        except AttributeError:
            rsc_goal = None

        aggregated = fundraise.get_contributors_summary()

        rsc_raised = sum(c.total_rsc for c in aggregated.top)
        usd_raised = sum(c.total_usd for c in aggregated.top)
        if fundraise.escrow:
            escrow_rsc = float(
                fundraise.escrow.amount_holding + fundraise.escrow.amount_paid
            )
            rsc_raised += escrow_rsc

        try:
            total_usd = usd_raised + (
                RscExchangeRate.rsc_to_usd(rsc_raised) if rsc_raised > 0 else 0
            )
            total_rsc = rsc_raised + (
                RscExchangeRate.usd_to_rsc(usd_raised) if usd_raised > 0 else 0
            )
        except AttributeError:
            total_usd = usd_raised
            total_rsc = rsc_raised

        contributors = []
        for entry in aggregated.top:
            profile_image = None
            author = getattr(entry.user, "author_profile", None)
            if author and author.profile_image:
                try:
                    profile_image = author.profile_image.url
                except ValueError:
                    profile_image = None

            contributors.append(
                {
                    "id": entry.user.id,
                    "first_name": entry.user.first_name,
                    "last_name": entry.user.last_name,
                    "profile_image": profile_image,
                    "total_contribution": {
                        "rsc": entry.total_rsc,
                        "rsc_usd_snapshot": entry.total_rsc_usd_snapshot,
                        "usd": entry.total_usd,
                    },
                }
            )

        nonprofit_data = None
        links = fundraise.nonprofit_links.all()
        if links:
            np = links[0].nonprofit
            nonprofit_data = {
                "id": np.id,
                "name": np.name,
                "ein": np.ein,
                "endaoment_org_id": np.endaoment_org_id,
            }

        reviews = [
            {
                "id": r.id,
                "score": r.score,
                "is_assessed": r.is_assessed,
                "author": cls._serialize_review_author(r),
            }
            for r in ud.reviews.all()
        ]

        assessed_scores = [r["score"] for r in reviews if r["is_assessed"]]
        review_metrics = {
            "avg": (
                sum(assessed_scores) / len(assessed_scores) if assessed_scores else 0
            ),
            "count": len(assessed_scores),
        }

        return {
            "id": fundraise.id,
            "title": post.title,
            "status": fundraise.status,
            "goal_amount": {"usd": usd_goal, "rsc": rsc_goal},
            "amount_raised": {
                "usd": total_usd,
                "rsc": total_rsc,
            },
            "contributors": {
                "total": aggregated.total,
                "top": contributors,
            },
            "nonprofit": nonprofit_data,
            "review_metrics": review_metrics,
            "reviews": reviews,
        }

    @staticmethod
    def _serialize_review_author(review):
        user = review.created_by
        if not user:
            return None
        author = getattr(user, "author_profile", None)
        if not author:
            return None
        profile_image = None
        if author.profile_image:
            try:
                profile_image = author.profile_image.url
            except ValueError:
                pass
        return {
            "id": author.id,
            "first_name": author.first_name,
            "last_name": author.last_name,
            "profile_image": profile_image,
        }
