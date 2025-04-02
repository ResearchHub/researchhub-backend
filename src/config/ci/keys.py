import os

SECRET_KEY = os.environ.get("SECRET_KEY", "test")

AWS_REGION_NAME = os.environ.get("AWS_REGION_NAME", "awsRegionName1")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME", "awsBucketName1")
AWS_SES_REGION_ENDPOINT = os.environ.get("AWS_SES_REGION_ENDPOINT", "")

EMAIL_WHITELIST = os.environ.get("EMAIL_WHITELIST", "no-one@researchhub.com")

GHOSTSCRIPT_LAMBDA_ARN = os.environ.get("GHOSTSCRIPT_LAMBDA_ARN", "NOT_REAL")

HEALTH_CHECK_TOKEN = os.environ.get("HEALTH_CHECK_TOKEN", "")

PERSONA_WEBHOOK_SECRET = os.environ.get("PERSONA_WEBHOOK_SECRET", "")

MAILCHIMP_KEY = os.environ.get("MAILCHIMP_KEY", "NOT_REAL")
MAILCHIMP_LIST_ID = os.environ.get("MAILCHIMP_LIST_ID", "NOT_REAL")

RECAPTCHA_SECRET_KEY = os.environ.get("RECAPTCHA_SECRET_KEY", "NOT_REAL")

SIFT_ACCOUNT_ID = os.environ.get("SIFT_ACCOUNT_ID", "NOT_REAL")
SIFT_REST_API_KEY = os.environ.get("SIFT_REST_API_KEY", "NOT_REAL")
SIFT_WEBHOOK_SECRET_KEY = os.environ.get("SIFT_WEBHOOK_SECRET_KEY", "NOT_REAL")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET", "")
STRIPE_WEBHOOK_SIGNING_SECRET = os.environ.get("STRIPE_WEBHOOK_SIGNING_SECRET", "")

AMPLITUDE_API_KEY = os.environ.get("AMPLITUDE_API_KEY", "NOT_REAL")

SENTRY_DSN = os.environ.get("SENTRY_DSN", "NOT_REAL")

APM_URL = os.environ.get("APM_URL", "NOT_REAL")

ELASTICSEARCH_HOST = os.environ.get("ELASTICSEARCH_HOST", "NOT_REAL")

CKEDITOR_CLOUD_ACCESS_KEY = os.environ.get("CKEDITOR_CLOUD_ACCESS_KEY", "NOT_REAL")
CKEDITOR_CLOUD_ENVIRONMENT_ID = os.environ.get(
    "CKEDITOR_CLOUD_ENVIRONMENT_ID", "NOT_REAL"
)

MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY", "")
WEB3_NETWORK = os.environ.get("WEB3_NETWORK", "")
WEB3_RSC_ADDRESS = os.environ.get("WEB3_RSC_ADDRESS", "")
WEB3_BASE_RSC_ADDRESS = os.environ.get("WEB3_BASE_RSC_ADDRESS", "")
WEB3_KEYSTORE_SECRET_ID = os.environ.get("WEB3_KEYSTORE_SECRET_ID", "")
WEB3_KEYSTORE_PASSWORD_SECRET_ID = os.environ.get(
    "WEB3_KEYSTORE_PASSWORD_SECRET_ID", ""
)
WEB3_WALLET_ADDRESS = os.environ.get("WEB3_WALLET_ADDRESS", "")
WEB3_PROVIDER_URL = os.environ.get("WEB3_PROVIDER_URL", "")
WEB3_BASE_PROVIDER_URL = os.environ.get("WEB3_BASE_PROVIDER_URL", "")
CROSSREF_LOGIN_ID = os.environ.get("CROSSREF_LOGIN_ID", "")
CROSSREF_LOGIN_PASSWORD = os.environ.get("CROSSREF_LOGIN_PASSWORD", "")

MJML_APP_ID = os.environ.get("MJML_APP_ID", "")
MJML_SECRET_KEY = os.environ.get("MJML_SECRET_KEY", "")

TRANSPOSE_KEY = os.environ.get("TRANSPOSE_KEY", "")

OPENALEX_KEY = os.environ.get("OPENALEX_KEY", "")
SEGMENT_WRITE_KEY = os.environ.get("SEGMENT_WRITE_KEY", "")

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
BASESCAN_API_KEY = os.environ.get("BASESCAN_API_KEY", "")
COIN_GECKO_API_KEY = os.environ.get("COIN_GECKO_API_KEY", "")
ENDAOMENT_ACCOUNT_ID = os.environ.get("ENDAOMENT_ACCOUNT_ID")
