from paper.aws_lambda import test
from researchhub.settings import TEST_ENV


def handler(event, context):
    return True, TEST_ENV
