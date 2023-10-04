from paper.models import Paper
from prediction_market.models import PredictionMarket


def get_prediction_market(paper_id):
    # get unified document
    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        raise Exception("Paper does not exist")
    unified_document = paper.unified_document

    # get prediction market
    try:
        prediction_market = PredictionMarket.objects.get(
            unified_document=unified_document,
            prediction_type=PredictionMarket.REPLICATION_PREDICTION,
            status=PredictionMarket.OPEN,
        )
    except PredictionMarket.DoesNotExist:
        raise Exception("Prediction market does not exist")

    return prediction_market


def create_prediction_market(paper_id):
    # get unified document
    try:
        paper = Paper.objects.get(id=paper_id)
    except Paper.DoesNotExist:
        raise Exception("Paper does not exist")
    unified_document = paper.unified_document

    # create prediction market
    prediction_market = PredictionMarket.objects.create(
        unified_document=unified_document,
        prediction_type=PredictionMarket.REPLICATION_PREDICTION,
        status=PredictionMarket.OPEN,
    )

    return prediction_market


def get_or_create_prediction_market(paper_id):
    try:
        prediction_market = get_prediction_market(paper_id)
    except Exception:
        prediction_market = create_prediction_market(paper_id)

    return prediction_market
