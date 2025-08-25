# Enhanced User Saved Lists

This module provides enhanced functionality for users to save and organize lists of documents on ResearchHub. The feature supports multiple lists per user, sharing capabilities, and graceful handling of deleted documents.

## Features

### Core Functionality
- **Multiple Lists**: Users can create and manage multiple named lists
- **Document Types**: Supports all unified document types (papers, posts, notes, etc.)
- **Descriptions & Tags**: Lists can have descriptions and metadata tags
- **Public/Private**: Lists can be made public or kept private

### Sharing & Permissions
- **Shareable Links**: Public lists can be shared via unique URLs
- **User Permissions**: Granular permission system (VIEW, EDIT, ADMIN)
- **Collaborative Lists**: Multiple users can view/edit lists based on permissions

### Document Deletion Handling
- **Graceful Deletion**: When documents are deleted, they remain in lists with deletion status
- **Snapshot Information**: Document titles and types are preserved
- **User Notification**: Users are informed when documents are no longer available

## Models

### UserSavedList
The main list model with enhanced features:

```python
class UserSavedList(DefaultAuthenticatedModel, SoftDeletableModel):
    list_name = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    is_public = models.BooleanField(default=False)
    share_token = models.CharField(max_length=50, unique=True, blank=True, null=True)
    tags = models.JSONField(default=list, blank=True)
```

**Key Features:**
- Inherits from `DefaultAuthenticatedModel` (created_by, updated_by, timestamps)
- Inherits from `SoftDeletableModel` (is_public, is_removed, is_removed_date)
- Automatic share token generation for public lists
- Unique constraint on (created_by, list_name)

### UserSavedEntry
Enhanced entry model that handles document deletion:

```python
class UserSavedEntry(DefaultAuthenticatedModel, SoftDeletableModel):
    parent_list = models.ForeignKey(UserSavedList, on_delete=models.CASCADE)
    unified_document = models.ForeignKey(ResearchhubUnifiedDocument, on_delete=models.SET_NULL, null=True, blank=True)
    document_deleted = models.BooleanField(default=False)
    document_deleted_date = models.DateTimeField(null=True, blank=True)
    document_title_snapshot = models.CharField(max_length=500, blank=True, null=True)
    document_type_snapshot = models.CharField(max_length=50, blank=True, null=True)
```

**Key Features:**
- Inherits from `DefaultAuthenticatedModel` and `SoftDeletableModel`
- `unified_document` can be null when document is deleted
- Automatic snapshot capture of document title and type
- Unique constraint on (parent_list, unified_document) when document exists

### UserSavedListPermission
Permission model for sharing lists:

```python
class UserSavedListPermission(DefaultAuthenticatedModel):
    list = models.ForeignKey(UserSavedList, on_delete=models.CASCADE, related_name="permissions")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    permission = models.CharField(max_length=10, choices=PERMISSION_CHOICES, default="VIEW")
```

**Key Features:**
- Inherits from `DefaultAuthenticatedModel`
- Unique constraint on (list, user)
- Permission choices: VIEW, EDIT, ADMIN

## API Endpoints

### List Management
- `GET /api/lists/` - List all accessible lists (owned + shared + public)
- `POST /api/lists/` - Create a new list
- `GET /api/lists/{id}/` - Get detailed list information with documents
- `PUT /api/lists/{id}/` - Update a list
- `DELETE /api/lists/{id}/` - Delete a list

### Document Management
- `POST /api/lists/{id}/add_document/` - Add document to list
- `POST /api/lists/{id}/remove_document/` - Remove document from list

### Permission Management
- `POST /api/lists/{id}/add_permission/` - Add user permission
- `POST /api/lists/{id}/remove_permission/` - Remove user permission
- `GET /api/lists/{id}/permissions/` - List all permissions

### Public Sharing
- `GET /shared/list/{share_token}/` - Access shared list (no authentication required)

## Usage Examples

### Creating a List
```python
# Via API
POST /api/lists/
{
    "list_name": "My Research Papers",
    "description": "Important papers for my thesis",
    "tags": ["machine-learning", "neuroscience"],
    "is_public": true
}
```

### Adding a Document
```python
# Via API
POST /api/lists/{list_id}/add_document/
{
    "u_doc_id": 12345
}

# Alternative using paper_id
POST /api/lists/{list_id}/add_document/
{
    "paper_id": 67890
}
```

### Sharing a List
```python
# Via API
POST /api/lists/{list_id}/add_permission/
{
    "username": "colleague@example.com",
    "permission": "EDIT"
}
```

### Accessing a Shared List
```python
# Via API (no authentication required)
GET /shared/list/{share_token}/
```

## Permission Levels

- **VIEW**: Can view the list and its documents
- **EDIT**: Can add/remove documents from the list
- **ADMIN**: Can manage permissions and delete the list

## Document Deletion Handling

When a document is deleted from ResearchHub:

1. **Signal Handler**: Automatically marks related entries as deleted
2. **Snapshot Preservation**: Document title and type are preserved
3. **User Experience**: Users see the document with deletion status
4. **Cleanup Command**: Management command to handle edge cases

### Signal Handler
```python
# Automatically triggered when ResearchhubUnifiedDocument is deleted
@receiver(pre_delete, sender=ResearchhubUnifiedDocument)
def handle_document_deletion(sender, instance, **kwargs):
    # Mark UserSavedEntry instances as deleted
    # Set document_deleted=True, document_deleted_date=now()
    # Set unified_document=None
```

### Management Command
```bash
# Clean up deleted document entries
python manage.py cleanup_deleted_documents

# Dry run to see what would be changed
python manage.py cleanup_deleted_documents --dry-run

# Process in smaller batches
python manage.py cleanup_deleted_documents --batch-size=50
```

## Database Migrations

The enhanced functionality requires database migrations:

```bash
# Create migrations
python manage.py makemigrations user_saved

# Apply migrations
python manage.py migrate user_saved
```

**Migration Files:**
- `0001_initial.py` - Creates initial models with some missing parent class fields
- `0002_usersavedlistpermission_and_more.py` - Adds missing fields and creates final schema

## Testing

Comprehensive tests are included in `tests.py`:

```bash
# Run all tests
python manage.py test user_saved

# Run specific test classes
python manage.py test user_saved.tests.UserSavedListAPITests
python manage.py test user_saved.tests.UserSavedSharedListAPITests
```

**Test Coverage:**
- Model functionality (creation, constraints, soft deletes)
- API endpoints (CRUD operations, permissions, sharing)
- Document deletion handling
- Permission system
- Share token generation

## Security Considerations

- **Authentication**: All API endpoints require authentication except shared list access
- **Authorization**: Permission checks ensure users can only access/modify lists they own or have permission for
- **Input Validation**: All inputs are validated through Django REST Framework serializers
- **SQL Injection**: Protected through Django ORM
- **XSS**: Protected through proper serialization and template rendering

## Performance Considerations

- **Database Indexes**: Optimized indexes for common query patterns
  - `idx_share_token` on UserSavedList.share_token
  - `idx_document_deleted` on UserSavedEntry.document_deleted
  - `idx_list_user_permission` on UserSavedListPermission
- **Soft Deletes**: Uses soft deletes to maintain referential integrity
- **Batch Operations**: Management commands support batch processing
- **Pagination**: API responses are paginated for large datasets

## API Response Examples

### List Detail Response
```json
{
    "id": 1,
    "list_name": "My Research Papers",
    "description": "Important papers for my thesis",
    "is_public": true,
    "share_url": "http://localhost:8000/shared/list/abc123...",
    "tags": ["machine-learning", "neuroscience"],
    "document_count": 5,
    "created_by_username": "researcher",
    "created_date": "2024-01-15T10:30:00Z",
    "documents": [
        {
            "id": 1,
            "document_info": {
                "id": 123,
                "title": "Deep Learning Advances",
                "type": "PAPER"
            },
            "is_deleted": false
        },
        {
            "id": 2,
            "document_info": null,
            "is_deleted": true,
            "document_title_snapshot": "Deleted Paper Title",
            "document_type_snapshot": "PAPER"
        }
    ],
    "permissions": [
        {
            "id": 1,
            "username": "colleague@example.com",
            "email": "colleague@example.com",
            "permission": "EDIT"
        }
    ]
}
```

### Shared List Response (No Auth Required)
```json
{
    "id": 1,
    "list_name": "Public Research Papers",
    "description": "Shared collection of papers",
    "is_public": true,
    "tags": ["public", "research"],
    "document_count": 3,
    "created_by_username": "researcher",
    "created_date": "2024-01-15T10:30:00Z",
    "documents": [
        {
            "entry_id": 1,
            "title": "Deep Learning Advances",
            "type": "PAPER",
            "is_deleted": false
        }
    ]
}
```

## Future Enhancements

Potential future improvements:

- **List Templates**: Pre-defined list templates for common use cases
- **Advanced Search**: Search within lists by document properties
- **List Analytics**: Usage statistics and insights
- **Export/Import**: Export lists to various formats
- **Notifications**: Notify users when shared lists are updated
- **Versioning**: Track changes to lists over time
- **Bulk Operations**: Add/remove multiple documents at once
- **List Categories**: Organize lists into categories or folders
