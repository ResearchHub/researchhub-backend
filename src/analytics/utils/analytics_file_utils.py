import csv
import json
import os

CHUNK_SIZE = 100


def read_last_processed_ids(filepath, models_to_export):
    if os.path.exists(filepath):
        with open(filepath, "r") as file:
            return json.load(file)

    return {key: 0 for key in models_to_export}


def write_last_processed_id(model_name, models_to_export, last_id, filepath):
    ids = read_last_processed_ids(filepath, models_to_export)
    ids[model_name] = last_id
    with open(filepath, "w") as file:
        json.dump(ids, file)


def truncate_fields(record, headers, max_length=900):
    for key, value in record.items():
        if isinstance(value, str) and len(value) > max_length:
            record[key] = value[:max_length]  # Truncate the string

    return {key: value for key, value in record.items() if key in headers}


def remove_file(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"file '{filepath}' has been removed.")
    except Exception as e:
        print(f"Error occurred while removing the file: {e}")


def write_data_to_csv(data, headers, output_filepath):
    # Check if the file already exists to determine whether to write headers
    file_exists = os.path.isfile(output_filepath)

    # Open the file in append mode instead of write mode
    with open(output_filepath, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=headers)

        # Write the header only if the file didn't exist
        if not file_exists:
            writer.writeheader()

        for item in data:
            truncated_item = truncate_fields(
                item, headers
            )  # Truncate fields before writing
            writer.writerow(truncated_item)


def export_data_to_csv_in_chunks(
    queryset,
    current_model_to_export,
    all_models_to_export,
    chunk_processor,
    headers,
    output_filepath,
    temp_progress_filepath,
    last_id=0,
):
    _last_id = last_id
    chunk_num = 1

    while True:
        _queryset = queryset.filter(id__gt=_last_id).order_by("id")[:CHUNK_SIZE]
        chunk = list(_queryset.iterator())

        if not chunk:
            break

        # Process the chunk with the provided function
        processed_chunk = chunk_processor(chunk)

        write_data_to_csv(processed_chunk, headers, output_filepath)

        print(f"Successfully exported chunk {chunk_num} {output_filepath}")

        # Move the pointers forward
        last_record = chunk[-1]
        _last_id = last_record.id
        chunk_num += 1
        # Write progress to temp file in case something goes wrong
        write_last_processed_id(
            current_model_to_export,
            all_models_to_export,
            _last_id,
            temp_progress_filepath,
        )

        # raise Exception("stop")
