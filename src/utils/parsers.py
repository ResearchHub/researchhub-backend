from django.utils.text import slugify

ISO_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def clean_filename(filename):
    filename_parts = filename.split(".")
    if len(filename_parts) > 1:
        extension = slugify(filename_parts[-1])
        return f"{slugify(filename_parts[0])}.{extension}"
    else:
        return slugify(filename)


def rebuild_sentence_from_inverted_index(index):
    if not isinstance(index, dict):
        return None

    reverse_index = {i: key for key, value in index.items() for i in value}
    sentence_array = [reverse_index[key] for key in sorted(reverse_index.keys())]
    return " ".join(sentence_array)
