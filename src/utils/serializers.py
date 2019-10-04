from rest_framework import serializers

from django.forms.models import model_to_dict
class BaseAcceptNestedModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        for f in self.Meta.model._meta.get_fields():
            if f.is_relation and f.name in data:
                data[f.name] = f.related_model.objects.get(pk=data.get(f.name))
        return data

class AcceptNestedModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        if type(data) == dict:
            if 'id' in data:
                return self.nested_helper(self.Meta.model, data, self.Meta.model.objects.get(id=data['id']), None, False)
            else:
                return self.nested_helper(self.Meta.model, data, self.instance, None, False)
        else:
            return model_to_dict(data)

    def nested_helper(self, model, data, instance=None, parent=None, create=False):
        if type(data) != dict:
            return data
        for f in model._meta.get_fields():
            if f.is_relation and f.name in data:
                if type(data.get(f.name)) == int:
                    data[f.name] = f.related_model.objects.get(pk=data.get(f.name))
                elif instance:
                    val = getattr(instance, f.name)
                    if val:
                        if type(data.get(f.name)) == list:
                            update_vals = []
                            for d in data[f.name]:
                                if type(d) == dict:
                                    if 'id' in d:
                                        update_vals.append(self.nested_helper(f.related_model, d, val.get(id=d['id']), instance, False))
                                    else:
                                        update_vals.append(self.nested_helper(f.related_model, d, None, instance, True))
                                else:
                                    update_vals.append(d)
                            data[f.name] = update_vals
                        elif type(data.get(f.name)) == dict:
                            for k, v in data[f.name].items():
                                setattr(val, k, v)
                            # TODO set parent class?
                            val.save()
                            data[f.name] = val
                    else:
                        data[f.name] = self.nested_helper(f.related_model, data.get(f.name), None, instance, True)
                else:
                    data[f.name] = self.nested_helper(f.related_model, data.get(f.name), None, instance, True)
            elif f.is_relation and parent and parent._meta.model == f.related_model:
                data[f.name] = parent
        if create:
            return model.objects.create(**data)
        else:
            return data

class BaseListSerializer(serializers.ListSerializer):
    def update(self, instance, validated_data):
        new = []
        current = []
        for d in validated_data:
            if 'id' in d and instance.filter(pk=d['id']).exists():
                current.append(self.child.update(instance.get(pk=d['id']), d))
            elif 'id' in d:
                print('unexpected behavior object has id but not prsent in db')
                self.child.create(d)
            else:
                self.child.create(d)

        #current = [self.child.update(instance.get(pk=d['id']), d) for d in validated_data if 'id' in d]
        #new = [self.child.create(d) for d in validated_data if 'id' not in d]
        return current + new
