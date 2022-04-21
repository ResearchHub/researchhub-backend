from review.serializers import ReviewSerializer

def create_review(data, unified_document, context):
    data['unified_document'] = unified_document.id
    
    serializer = ReviewSerializer(data=data, context=context)
    serializer.is_valid()
    review = serializer.create(serializer.validated_data)
    return review