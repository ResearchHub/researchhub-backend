# Ignore this file for now
# Will probably delete this later
# Using Thread.clean to validate metadata

from django.core.exceptions import ValidationError
# import jsonschema

from django.core.validators import BaseValidator

THREAD_SOURCE_SCHEMA = {
    'type': 'object',
    'properties': {
        'my_key': {
            'type': 'string'
        }
    },
    'required': ['inline_paper_body']
}


class JSONSchemaValidator(BaseValidator):
    def compare(self, inputs, schema):
        return True
        # try:
        #     jsonschema.validate(inputs, schema)
        # except jsonschema.exceptions.ValidationError:
        #     raise django.core.exceptions.ValidationError(
        #         f'{inputs} failed JSON schema check'
        #     )


# class ThreadValidator(BaseValidator):
#     def compare(self, input_value, schema):
#         import pdb; pdb.set_trace()


def ThreadValidator(value):
    raise ValidationError(value)
    # import pdb; pdb.set_trace()
    # print('test')
    # return True
