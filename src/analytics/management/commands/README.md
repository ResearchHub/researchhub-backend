# User Interactions Sync Command

## Overview

The `sync_user_interactions` management command allows you to import interaction data into the `UserInteractions` table and export it to AWS Personalize CSV format.

## Usage

### Import Mode

Import interaction data from source tables using mapper classes:

```bash
# Import all interactions
python manage.py sync_user_interactions --mode import

# Import with date range filtering
python manage.py sync_user_interactions --mode import --start-date 2024-01-01 --end-date 2024-12-31

# Import with custom batch size
python manage.py sync_user_interactions --mode import --batch-size 500
```

**Features:**
- Imports upvote interactions using the `map_from_upvote()` function
- Uses `bulk_create()` with `ignore_conflicts=True` to handle duplicates
- Processes in batches for memory efficiency (default: 1000 records)
- Displays progress and creation statistics

### Export Mode

Export `UserInteractions` to AWS Personalize Interactions dataset CSV format:

```bash
# Export all interactions (creates timestamped file)
python manage.py sync_user_interactions --mode export

# Export to custom filename
python manage.py sync_user_interactions --mode export --output-file my_export.csv

# Export with date range filtering
python manage.py sync_user_interactions --mode export --start-date 2024-01-01 --end-date 2024-12-31

# Combine options
python manage.py sync_user_interactions --mode export --output-file personalize_data.csv --start-date 2024-06-01
```

**Output Format (AWS Personalize Interactions):**
```csv
USER_ID,ITEM_ID,TIMESTAMP,EVENT_TYPE
123,456,1635784800,UPVOTE
124,457,1635784900,UPVOTE
```

**Features:**
- Exports to CSV with AWS Personalize Interactions format
- Default filename: `user_interactions_export_YYYYMMDD_HHMMSS.csv`
- Filters records by date range (optional)
- Skips records with missing user or document IDs
- Displays export statistics

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `--mode` | Yes | Operation mode: `import` or `export` |
| `--start-date` | No | Start date filter (YYYY-MM-DD format) |
| `--end-date` | No | End date filter (YYYY-MM-DD format) |
| `--output-file` | No | Output filename for export mode |
| `--batch-size` | No | Batch size for import operations (default: 1000) |

## Adding New Interaction Types

To add support for new interaction types:

1. **Add mapping function** in `analytics/interactions/interaction_mapper.py`:
   ```python
   def map_from_click(click: Click) -> UserInteractions:
       """Map a Click record to UserInteractions instance."""
       return UserInteractions(...)
   ```

2. **Add queryset method** in the management command:
   ```python
   def _get_click_queryset(self, start_date, end_date):
       """Get filtered queryset of click records."""
       queryset = Click.objects.filter(...)
       # Apply date filters
       return queryset
   ```

3. **Update handle_import()** to process the new interaction type

4. **Export the function** in `analytics/interactions/__init__.py`

5. **Add event type** to `analytics/constants/event_types.py` if needed

## Example Workflow

1. **Initial data import:**
```bash
python manage.py sync_user_interactions --mode import
```

2. **Export for AWS Personalize:**
```bash
python manage.py sync_user_interactions --mode export --output-file personalize_interactions.csv
```

3. **Incremental updates (import recent data):**
```bash
python manage.py sync_user_interactions --mode import --start-date 2024-10-01
```

4. **Export specific time period:**
```bash
python manage.py sync_user_interactions --mode export --start-date 2024-01-01 --end-date 2024-10-28 --output-file Q1_Q3_2024.csv
```

