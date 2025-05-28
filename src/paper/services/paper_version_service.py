from paper.models import Paper
from paper.related_models.paper_version import PaperVersion


class PaperVersionService:
    @staticmethod
    def get_all_paper_versions(paper_id):
        """
        Get all versions of a paper including the original.

        Args:
            paper_id: ID of any paper in the version chain

        Returns:
            List of Paper objects that are versions of the same paper
        """
        try:
            # Try to get the paper
            paper = Paper.objects.get(id=paper_id)

            # First try to get this paper's version to find the original
            try:
                paper_version = PaperVersion.objects.get(paper=paper)

                # If this is a version, get the original paper
                if paper_version.original_paper:
                    original_paper_id = paper_version.original_paper.id
                else:
                    original_paper_id = paper_id
            except PaperVersion.DoesNotExist:
                # If this paper has no version, check if it's an original paper for other versions
                original_paper_id = paper_id

            # Get all papers related to this original paper
            paper_versions = PaperVersion.objects.filter(
                original_paper_id=original_paper_id
            )

            # Collect all paper IDs (original + versions)
            paper_ids = [original_paper_id]
            paper_ids.extend([version.paper_id for version in paper_versions])

            # Remove duplicates and fetch actual papers
            return Paper.objects.filter(id__in=set(paper_ids))
        except Paper.DoesNotExist:
            # If the paper doesn't exist, return an empty queryset
            return Paper.objects.none()
