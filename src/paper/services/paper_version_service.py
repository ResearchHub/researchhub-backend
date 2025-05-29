from paper.models import Paper
from paper.related_models.paper_version import PaperVersion


class PaperService:
    """
    Service for paper-related operations including version management.

    This service handles both regular paper operations and paper version management,
    making it easier to test and extend with dependency injection.
    """

    def __init__(self, paper_model=None, paper_version_model=None):
        """
        Initialize the service with optional model dependencies for testing.

        Args:
            paper_model: Paper model class (defaults to Paper)
            paper_version_model: PaperVersion model class (defaults to PaperVersion)
        """
        self.paper_model = paper_model or Paper
        self.paper_version_model = paper_version_model or PaperVersion

    def get_all_paper_versions(self, paper_id):
        """
        Get all versions of a paper including the original.

        Args:
            paper_id: ID of any paper in the version chain

        Returns:
            QuerySet of Paper objects that are versions of the same paper
        """
        try:
            # Try to get the paper
            paper = self.paper_model.objects.get(id=paper_id)

            # First try to get this paper's version to find the original
            try:
                paper_version = self.paper_version_model.objects.get(paper=paper)

                # If this is a version, get the original paper
                if paper_version.original_paper:
                    original_paper_id = paper_version.original_paper.id
                else:
                    original_paper_id = paper_id
            except self.paper_version_model.DoesNotExist:
                # If this paper has no version, check if it's an original paper for other versions
                original_paper_id = paper_id

            # Get all papers related to this original paper
            paper_versions = self.paper_version_model.objects.filter(
                original_paper_id=original_paper_id
            )

            # Collect all paper IDs (original + versions)
            paper_ids = [original_paper_id]
            paper_ids.extend([version.paper_id for version in paper_versions])

            # Remove duplicates and fetch actual papers
            return self.paper_model.objects.filter(id__in=set(paper_ids))
        except self.paper_model.DoesNotExist:
            # If the paper doesn't exist, return an empty queryset
            return self.paper_model.objects.none()

    def get_original_paper(self, paper_id):
        """
        Get the original paper for a given paper ID.

        Args:
            paper_id: ID of any paper in the version chain

        Returns:
            Paper object that is the original paper, or None if not found
        """
        try:
            paper = self.paper_model.objects.get(id=paper_id)

            try:
                paper_version = self.paper_version_model.objects.get(paper=paper)
                return paper_version.original_paper or paper
            except self.paper_version_model.DoesNotExist:
                # This paper is either the original or has no versions
                return paper
        except self.paper_model.DoesNotExist:
            return None

    def is_paper_version(self, paper_id):
        """
        Check if a paper is a version of another paper.

        Args:
            paper_id: ID of the paper to check

        Returns:
            bool: True if the paper is a version, False otherwise
        """
        try:
            paper = self.paper_model.objects.get(id=paper_id)
            paper_version = self.paper_version_model.objects.get(paper=paper)
            return paper_version.original_paper is not None
        except (self.paper_model.DoesNotExist, self.paper_version_model.DoesNotExist):
            return False
