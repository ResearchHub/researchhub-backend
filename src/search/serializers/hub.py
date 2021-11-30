from rest_framework import serializers

from hub.models import Hub


class HubDocumentSerializer(serializers.ModelSerializer):
    slug = serializers.SerializerMethodField()
    hub_image = serializers.SerializerMethodField()

    def get_slug(self, hit):
        slug = ''
        try:
            obj = Hub.objects.get(id=hit['id'])
            slug = obj.slug
        except Exception as e:
            print(e)
            pass

        return slug

    def get_hub_image(self, hit):
        img = ''
        try:
            obj = Hub.objects.get(id=hit['id'])
            img = obj.hub_image.url
        except Exception as e:
            print(e)
            pass

        return img        

    class Meta(object):
        model = Hub
        fields = [
            'id',
            'name',
            'acronym',
            'description',
            'is_locked',
            'hub_image',
            'paper_count',
            'subscriber_count',
            'discussion_count',
            'slug',
        ]
