"""
Management command to seed Hub categories and subcategories.
This replaces the master_categories.py file and serves as the single source of truth.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from hub.models import Hub, HubCategory


class Command(BaseCommand):
    help = "Seed Hub table with predefined categories and subcategories"

    # Master category and subcategory structure
    # This is the single source of truth for all categories
    MASTER_CATEGORIES = {
        "Biology": [
            "Biochemistry",
            "Bioinformatics",
            "Biophysics",
            "Cancer Biology",
            "Cell Biology",
            "Developmental Biology",
            "Ecology",
            "Evolutionary Biology",
            "Genetics",
            "Genomics",
            "Immunology",
            "Microbiology",
            "Molecular Biology",
            "Neuroscience",
            "Paleontology",
            "Pathology",
            "Pharmacology",
            "Physiology",
            "Plant Biology",
            "Systems Biology",
            "Synthetic Biology",
            "Toxicology",
            "Zoology",
        ],
        "Medicine": [
            "Anesthesiology",
            "Cardiology",
            "Clinical Trials",
            "Critical Care Medicine",
            "Dentistry",
            "Dermatology",
            "Emergency Medicine",
            "Epidemiology",
            "Genetics and Genomics",
            "Health Economics",
            "Health Informatics",
            "Health Policy",
            "Internal Medicine",
            "Medical Education",
            "Medical Ethics",
            "Medical Physics",
            "Neurology",
            "Nursing",
            "Nutrition",
            "Obstetrics and Gynecology",
            "Oncology",
            "Ophthalmology",
            "Pain Medicine",
            "Pediatrics",
            "Psychiatry",
            "Public Health",
            "Radiology",
            "Rehabilitation Medicine",
            "Reproductive Health",
            "Sports Medicine",
            "Surgery",
            "Translational Medicine",
        ],
        "Computer Science": [
            "Artificial Intelligence",
            "Computational Complexity",
            "Computational Geometry",
            "Computer Vision",
            "Cryptography and Security",
            "Data Structures and Algorithms",
            "Databases",
            "Distributed Computing",
            "Formal Languages",
            "Game Theory",
            "Graphics",
            "Hardware Architecture",
            "Human-Computer Interaction",
            "Information Retrieval",
            "Machine Learning",
            "Natural Language Processing",
            "Neural Computing",
            "Networking",
            "Operating Systems",
            "Programming Languages",
            "Robotics",
            "Software Engineering",
            "Sound",
        ],
        "Physics": [
            "Astrophysics",
            "Atomic Physics",
            "Computational Physics",
            "Condensed Matter",
            "Cosmology",
            "Fluid Dynamics",
            "General Relativity",
            "Geophysics",
            "High Energy Experiment",
            "High Energy Phenomenology",
            "High Energy Theory",
            "Instrumentation",
            "Lattice Physics",
            "Mathematical Physics",
            "Nuclear Experiment",
            "Nuclear Theory",
            "Optics",
            "Plasma Physics",
            "Quantum Physics",
            "Statistical Mechanics",
        ],
        "Mathematics": [
            "Algebraic Geometry",
            "Algebraic Topology",
            "Analysis of PDEs",
            "Category Theory",
            "Classical Analysis",
            "Combinatorics",
            "Commutative Algebra",
            "Complex Variables",
            "Differential Geometry",
            "Discrete Mathematics",
            "Dynamical Systems",
            "Functional Analysis",
            "General Mathematics",
            "General Topology",
            "Geometric Topology",
            "Group Theory",
            "History and Overview",
            "Information Theory",
            "K-Theory",
            "Logic",
            "Metric Geometry",
            "Number Theory",
            "Numerical Analysis",
            "Operator Algebras",
            "Optimization and Control",
            "Probability",
            "Quantum Algebra",
            "Representation Theory",
            "Rings and Algebras",
            "Spectral Theory",
            "Symplectic Geometry",
        ],
        "Chemistry": [
            "Chemical Physics",
            "Organic Chemistry",
            "Inorganic Chemistry",
            "Physical Chemistry",
            "Analytical Chemistry",
        ],
        "Engineering": [
            "Audio and Speech Processing",
            "Bioengineering",
            "Computational Engineering",
            "Image and Video Processing",
            "Signal Processing",
            "Systems and Control",
        ],
        "Economics": [
            "Computational Finance",
            "Econometrics",
            "Economic Theory",
            "Financial Economics",
            "General Economics",
            "General Finance",
            "Mathematical Finance",
            "Portfolio Management",
            "Quantitative Finance",
            "Risk Management",
            "Securities Pricing",
            "Statistical Finance",
            "Trading and Market Microstructure",
        ],
        "Statistics": [
            "Applications",
            "Computation",
            "Methodology",
            "Statistics Theory",
        ],
        "Social Sciences": [
            "Physics and Society",
            "Scientific Communication and Education",
        ],
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without making changes",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed output",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        verbose = options["verbose"]

        self.stdout.write(
            self.style.WARNING(
                f"{'DRY RUN: ' if dry_run else ''}"
                "Seeding HubCategories and subcategories..."
            )
        )

        # Track what needs to be created
        hub_categories_to_create = []
        hub_categories_to_skip = []
        subcategories_to_create = []
        subcategories_to_skip = []
        hubs_to_update_category = []

        # First, process HubCategory objects
        for category_name in self.MASTER_CATEGORIES.keys():
            # Check if HubCategory already exists (case-insensitive)
            existing_hub_category = HubCategory.objects.filter(
                category_name__iexact=category_name
            ).first()

            if existing_hub_category:
                hub_categories_to_skip.append(
                    (category_name, existing_hub_category.category_name)
                )
            else:
                hub_categories_to_create.append(category_name)

        # Process subcategories
        for category_name, subcategories in self.MASTER_CATEGORIES.items():
            # Get the HubCategory for this category
            hub_category = HubCategory.objects.filter(
                category_name__iexact=category_name
            ).first()

            for subcategory_name in subcategories:
                # Check if subcategory hub already exists (case-insensitive)
                existing_subcategory = Hub.objects.filter(
                    Q(name__iexact=subcategory_name) & Q(namespace="subcategory")
                ).first()

                if existing_subcategory:
                    subcategories_to_skip.append(
                        (subcategory_name, existing_subcategory.name, category_name)
                    )

                    # Check if it needs its category updated
                    if hub_category and existing_subcategory.category != hub_category:
                        hubs_to_update_category.append(
                            (existing_subcategory, hub_category, "subcategory")
                        )
                else:
                    subcategories_to_create.append((subcategory_name, category_name))

        # Display summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 60)

        # HubCategory summary
        self.stdout.write(f"\nHubCategories to create: {len(hub_categories_to_create)}")
        if verbose and hub_categories_to_create:
            for cat in hub_categories_to_create:
                self.stdout.write(f"  + {cat}")

        self.stdout.write(f"\nHubCategories to skip: {len(hub_categories_to_skip)}")
        if verbose and hub_categories_to_skip:
            for new_name, existing_name in hub_categories_to_skip:
                if new_name != existing_name:
                    self.stdout.write(f"  - {new_name} (exists as '{existing_name}')")
                else:
                    self.stdout.write(f"  - {new_name}")

        # Subcategories summary
        self.stdout.write(f"\nSubcategories to create: {len(subcategories_to_create)}")
        if verbose and subcategories_to_create:
            for subcat, cat in subcategories_to_create:
                self.stdout.write(f"  + {subcat} (under {cat})")

        self.stdout.write(f"\nSubcategories to skip: {len(subcategories_to_skip)}")
        if verbose and subcategories_to_skip:
            for new_name, existing_name, cat in subcategories_to_skip:
                if new_name != existing_name:
                    self.stdout.write(
                        f"  - {new_name} (exists as '{existing_name}' under {cat})"
                    )
                else:
                    self.stdout.write(f"  - {new_name} (under {cat})")

        # Hubs to update category summary
        self.stdout.write(
            f"\n\nHubs to update category: {len(hubs_to_update_category)}"
        )
        if verbose and hubs_to_update_category:
            for hub, hub_cat, hub_type in hubs_to_update_category:
                self.stdout.write(
                    f"  ~ {hub.name} ({hub_type}) -> "
                    f"category: {hub_cat.category_name}"
                )

        self.stdout.write("\n" + "=" * 60 + "\n")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN completed. No changes were made.")
            )
            return

        # Perform the actual creation
        if (
            hub_categories_to_create
            or subcategories_to_create
            or hubs_to_update_category
        ):
            try:
                with transaction.atomic():
                    # Create HubCategory objects
                    for category_name in hub_categories_to_create:
                        HubCategory.objects.create(category_name=category_name)
                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Created HubCategory: {category_name}"
                                )
                            )

                    # Create subcategories
                    for subcategory_name, category_name in subcategories_to_create:
                        # Get the HubCategory
                        hub_category = HubCategory.objects.get(
                            category_name__iexact=category_name
                        )

                        Hub.objects.create(
                            name=subcategory_name,
                            namespace="subcategory",
                            category=hub_category,
                            description=(
                                f"{subcategory_name} - subcategory of {category_name}"
                            ),
                        )
                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Created subcategory hub: {subcategory_name} "
                                    f"under {category_name}"
                                )
                            )

                    # Update hubs that need their category_id updated
                    for hub, hub_category, hub_type in hubs_to_update_category:
                        hub.category = hub_category
                        hub.save(update_fields=["category"])
                        if verbose:
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"Updated {hub.name} ({hub_type}) "
                                    f"category to {hub_category.category_name}"
                                )
                            )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nSuccessfully processed:\n"
                        f"  - Created {len(hub_categories_to_create)} HubCategories\n"
                        f"  - Created {len(subcategories_to_create)} subcategory hubs\n"
                        f"  - Updated {len(hubs_to_update_category)} hub categories"
                    )
                )

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error during creation: {str(e)}"))
                raise
        else:
            self.stdout.write(
                self.style.SUCCESS("No new hubs need to be created. All already exist.")
            )

    @classmethod
    def get_master_categories(cls):
        """
        Return the master categories dictionary.
        This can be imported by other modules that need the category structure.
        """
        return cls.MASTER_CATEGORIES
