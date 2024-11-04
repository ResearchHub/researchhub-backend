import os

SECRET_KEY = os.environ.get("SECRET_KEY", "development")

AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "")
AWS_ROLE_ARN = os.environ.get("AWS_ROLE_ARN", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "")
AWS_SES_REGION_ENDPOINT = os.environ.get("AWS_SES_REGION_ENDPOINT", "")

GHOSTSCRIPT_LAMBDA_ARN = os.environ.get("GHOSTSCRIPT_LAMBDA_ARN", "")

PERSONA_WEBHOOK_SECRET = os.environ.get("PERSONA_WEBHOOK_SECRET", "")

MAILCHIMP_KEY = os.environ.get("MAILCHIMP_KEY", "")
MAILCHIMP_LIST_ID = os.environ.get("MAILCHIMP_LIST_ID", "")

RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "")

SIFT_ACCOUNT_ID = os.environ.get("SIFT_ACCOUNT_ID", "PLACEHOLDER")
SIFT_REST_API_KEY = os.environ.get("SIFT_REST_API_KEY", "PLACEHOLDER")
SIFT_WEBHOOK_SECRET_KEY = os.environ.get("SIFT_WEBHOOK_SECRET_KEY", "")

AMPLITUDE_API_KEY = os.environ.get("AMPLITUDE_API_KEY", "")

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "")

SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

APM_URL = os.environ.get("APM_URL", "")

ELASTICSEARCH_HOST = os.environ.get("ELASTICSEARCH_HOST", "")

CKEDITOR_CLOUD_ACCESS_KEY = os.environ.get("CKEDITOR_CLOUD_ACCESS_KEY", "")
CKEDITOR_CLOUD_ENVIRONMENT_ID = os.environ.get("CKEDITOR_CLOUD_ENVIRONMENT_ID", "")

CROSSREF_LOGIN_ID = os.environ.get("CROSSREF_LOGIN_ID", "")
CROSSREF_LOGIN_PASSWORD = os.environ.get("CROSSREF_LOGIN_PASSWORD", "")

MJML_APP_ID = os.environ.get("MJML_APP_ID", "")
MJML_SECRET_KEY = os.environ.get("MJML_SECRET_KEY", "")

MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY", "")
WEB3_NETWORK = os.environ.get("WEB3_NETWORK", "")
WEB3_KEYSTORE_BUCKET = os.environ.get("WEB3_KEYSTORE_BUCKET", "")
WEB3_KEYSTORE_FILE = os.environ.get("WEB3_KEYSTORE_FILE", "")
WEB3_KEYSTORE_PASSWORD = os.environ.get("WEB3_KEYSTORE_PASSWORD", "")
WEB3_RSC_ADDRESS = os.environ.get("WEB3_RSC_ADDRESS", "")
WEB3_WALLET_ADDRESS = os.environ.get("WEB3_WALLET_ADDRESS", "")
WEB3_PROVIDER_URL = os.environ.get("WEB3_PROVIDER_URL", "")

TRANSPOSE_KEY = os.environ.get("TRANSPOSE_KEY", "")
OPENALEX_KEY = os.environ.get("OPENALEX_KEY", "")
SEGMENT_WRITE_KEY = os.environ.get("SEGMENT_WRITE_KEY", "")

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
COIN_GECKO_API_KEY = os.environ.get("COIN_GECKO_API_KEY", "")
