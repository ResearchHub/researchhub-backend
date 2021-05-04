from paper.aws_lambda import test


def handler(event, context):
    return True, test()
