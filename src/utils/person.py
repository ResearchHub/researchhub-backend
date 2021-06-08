from django.db import models

def get_name(person):
    print(person)
    full_name = []

    if isinstance(person, models.Model) or isinstance(person, models.Model):
        if getattr(person, 'first_name') and isinstance(getattr(person, 'first_name'), str):
            full_name.append(person.first_name)
        if getattr(person, 'last_name') and isinstance(getattr(person, 'last_name'), str):
            full_name.append(person.last_name)

    elif isinstance(person, dict):
        if person.get('first_name') and isinstance(person.get('first_name'), str):
            full_name.append(person.get('first_name'))
        if person.get('last_name') and isinstance(person.get('last_name'), str):
            full_name.append(person.get('last_name'))

    return ' '.join(full_name)
