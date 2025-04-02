# Feed Management Commands

This directory contains management commands for handling feed-related operations in ResearchHub.

## populate_feed.py

Populates feed entries for both comments and papers in a single command, with unified document and hubs.
This is useful for bootstrapping the feed when it's empty or needs repopulation.

```bash
# Basic usage - populate feed entries for both comments and papers
python manage.py populate_feed

# Process only papers
python manage.py populate_feed --papers-only

# Process only comments
python manage.py populate_feed --comments-only

# Dry run - show what would happen without making changes
python manage.py populate_feed --dry-run

# Force recreate feed entries even if they already exist
python manage.py populate_feed --force

# Specify a custom batch size for processing
python manage.py populate_feed --batch-size=500
```

### Notes

- The command only creates feed entries for items that are:
  - Not removed (`is_removed=False`)
  - Associated with a unified document
  - Associated with a unified document that has at least one hub
  - For papers, they must have a publish date (`paper_publish_date` not null)

- By default, the command will skip items that already have feed entries for their hubs
  - Use `--force` to recreate entries even if they already exist

- Progress information is displayed every 100 items and at completion

## populate_feed_entries.py

Populates or updates metrics and content for existing feed entries.

```bash
# To update only empty metrics
python manage.py populate_feed_entries

# To update all metrics regardless of current state
python manage.py populate_feed_entries --all

# To update only metrics
python manage.py populate_feed_entries --metrics-only

# To update only content
python manage.py populate_feed_entries --content-only
```

## populate_comment_feed.py

Populates feed entries for all existing comments that have a unified document with hubs.
This is useful when the feed is empty or when comment feed entries are missing.

```bash
# Basic usage - populate feed entries for all comments
python manage.py populate_comment_feed

# Dry run - show what would happen without making changes
python manage.py populate_comment_feed --dry-run

# Force recreate feed entries even if they already exist
python manage.py populate_comment_feed --force

# Specify a custom batch size for processing
python manage.py populate_comment_feed --batch-size=500
```

### Notes

- The command only creates feed entries for comments that are:
  - Not removed (`is_removed=False`)
  - Associated with a thread that has a unified document
  - Associated with a unified document that has at least one hub

- By default, the command will skip comments that already have feed entries for their hubs
  - Use `--force` to recreate entries even if they already exist

- Progress information is displayed every 100 comments and at completion
