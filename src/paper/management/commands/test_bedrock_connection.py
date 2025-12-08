"""
Management command to test AWS Bedrock connection and configuration.
"""

import json

from django.core.management.base import BaseCommand
from django.conf import settings

from utils import aws as aws_utils


class Command(BaseCommand):
    help = "Test AWS Bedrock connection and configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--test-api",
            action="store_true",
            help="Test actual API call to Bedrock",
        )

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("AWS BEDROCK CONNECTION TEST")
        self.stdout.write("=" * 60 + "\n")

        # Check configuration
        self._check_configuration()

        # Test client creation
        self._test_client_creation()

        # Test API call if requested
        if options["test_api"]:
            self._test_api_call()

        self.stdout.write("\n" + "=" * 60)

    def _check_configuration(self):
        """Check configuration values."""
        self.stdout.write("1. Configuration Check:")
        self.stdout.write("-" * 60)

        model_id = getattr(settings, "AWS_BEDROCK_MODEL_ID", None)
        region = getattr(settings, "AWS_BEDROCK_REGION", None)
        aws_region = getattr(settings, "AWS_REGION_NAME", None)

        if model_id:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Model ID: {model_id}"))
        else:
            self.stdout.write(
                self.style.ERROR("  ✗ Model ID: Not configured")
            )

        if region:
            self.stdout.write(self.style.SUCCESS(f"  ✓ Bedrock Region: {region}"))
        else:
            self.stdout.write(
                self.style.WARNING(f"  ⚠ Bedrock Region: Not set (using {aws_region})")
            )

        if aws_region:
            self.stdout.write(self.style.SUCCESS(f"  ✓ AWS Region: {aws_region}"))
        else:
            self.stdout.write(self.style.ERROR("  ✗ AWS Region: Not configured"))

        self.stdout.write("")

    def _test_client_creation(self):
        """Test Bedrock client creation."""
        self.stdout.write("2. Client Creation Test:")
        self.stdout.write("-" * 60)

        try:
            bedrock_client = aws_utils.create_bedrock_client()
            self.stdout.write(
                self.style.SUCCESS("  ✓ Bedrock client created successfully")
            )
            self.stdout.write(f"    Service: bedrock-runtime")
            self.stdout.write(f"    Region: {bedrock_client.meta.region_name}")
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  ✗ Failed to create client: {e}")
            )
            self.stdout.write(
                self.style.WARNING(
                    "    Check AWS credentials and IAM permissions"
                )
            )

        self.stdout.write("")

    def _test_api_call(self):
        """Test actual API call to Bedrock."""
        self.stdout.write("3. API Call Test:")
        self.stdout.write("-" * 60)

        try:
            bedrock_client = aws_utils.create_bedrock_client()
            model_id = getattr(settings, "AWS_BEDROCK_MODEL_ID", None)

            if not model_id:
                self.stdout.write(
                    self.style.ERROR("  ✗ Cannot test: Model ID not configured")
                )
                return

            # Simple test request
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 100,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Say 'Hello, Bedrock!' and nothing else.",
                            }
                        ],
                    }
                ],
            }

            self.stdout.write(f"  Calling model: {model_id}...")

            response = bedrock_client.invoke_model(
                modelId=model_id,
                body=json.dumps(request_body),
            )

            response_body = json.loads(response["body"].read())

            if "content" in response_body:
                text_content = response_body["content"][0].get("text", "")
                self.stdout.write(
                    self.style.SUCCESS("  ✓ API call successful!")
                )
                self.stdout.write(f"    Response: {text_content[:100]}")
            else:
                self.stdout.write(
                    self.style.WARNING("  ⚠ Unexpected response format")
                )
                self.stdout.write(f"    Response: {response_body}")

        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)
            
            if "AccessDenied" in error_type or "access denied" in error_message.lower():
                self.stdout.write(
                    self.style.ERROR("  ✗ Access Denied")
                )
                self.stdout.write(
                    self.style.WARNING(
                        "    Check IAM permissions and model access in Bedrock Console"
                    )
                )
            elif "Validation" in error_type or "validation" in error_message.lower():
                self.stdout.write(
                    self.style.ERROR(f"  ✗ Validation Error: {error_message}")
                )
                self.stdout.write(
                    self.style.WARNING("    Check model ID is correct")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"  ✗ API call failed: {error_message}")
                )
                self.stdout.write(
                    self.style.WARNING("    Check AWS credentials and network")
                )

        self.stdout.write("")

