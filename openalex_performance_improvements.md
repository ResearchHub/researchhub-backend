# OpenAlex Works Processing Performance Improvements

## API Calls Optimization

- [ ] **Batch full work requests**: When works have truncated authors, collect IDs and fetch them in batches instead of individual calls
- [ ] **Cache OpenAlex responses**: Implement caching for OpenAlex responses to prevent redundant API calls
- [ ] **Implement throttling and backoff**: Add proper throttling and exponential backoff for API calls to prevent rate limiting
- [ ] **Prefetch all required data**: Analyze all data needed from OpenAlex and fetch it in fewer, more comprehensive requests

## Database Operations

- [ ] **Replace individual saves with bulk operations**: Eliminate `researchhub_author.save()` calls in `merge_openalex_author_with_researchhub_author()`
- [ ] **Use bulk add for M2M relationships**: Replace individual `authorship.institutions.add(institution)` with bulk operations
- [ ] **Collect and execute in batches**: Collect objects throughout loops and execute create/update operations once after loops complete
- [ ] **Optimize transaction handling**: Use transactions more effectively to reduce database overhead
- [ ] **Implement efficient upserts**: Use Django's bulk create/update with `update_conflicts=True` consistently

## Query Pattern Improvements

- [ ] **Replace Q-object chains**: Instead of building large Q-objects with many OR conditions for DOIs, use more efficient list operations
- [ ] **Optimize field selection**: Use `select_related()` and `only()` consistently to retrieve only needed fields
- [ ] **Avoid refetching data**: Eliminate the final database query in `create_authors()` that refetches all authors
- [ ] **Reduce database roundtrips**: Collect IDs and perform bulk lookups instead of individual object retrievals
- [ ] **Use more efficient lookups**: Replace lookups that generate complex queries with simpler, indexed lookups

## Data Processing Efficiency

- [ ] **Optimize coauthor creation**: Rewrite the nested loop in `create_coauthors()` to reduce O(n²) complexity
- [ ] **Pre-allocate collections**: Pre-allocate collections where size is known to reduce memory allocations
- [ ] **Replace list extensions**: Use set operations or more efficient data structures instead of extending lists in loops
- [ ] **Remove debug prints**: Eliminate print statements like `print(f"Processing authorships for paper: {related_paper.title}")` from production code
- [ ] **Use generators where appropriate**: Replace list comprehensions with generators for memory efficiency

## Concurrency and Parallelization

- [ ] **Add async/concurrent processing**: Implement parallel processing for independent operations like author processing
- [ ] **Use bulk operations for independent tasks**: Process batches of works concurrently instead of sequentially
- [ ] **Implement worker pools**: Use worker pools for IO-bound operations like API calls and database operations
- [ ] **Add progress tracking**: Implement proper progress tracking to monitor long-running operations
- [ ] **Consider celery tasks**: Break down the process into smaller Celery tasks that can run in parallel

## Monitoring and Profiling

- [ ] **Add performance metrics**: Instrument the code with timing metrics to identify bottlenecks
- [ ] **Implement logging**: Replace print statements with proper logging for better observability
- [ ] **Profile with realistic data**: Test with production-like data volumes to identify scaling issues
- [ ] **Add monitoring for rate limits**: Monitor API rate limits to avoid hitting them during processing
- [ ] **Implement circuit breakers**: Add circuit breakers to prevent cascading failures when external services are slow

## Schema Optimizations

- [ ] **Review indexes**: Ensure appropriate indexes exist for all lookup patterns
- [ ] **Optimize data types**: Review column data types for efficiency (e.g., using array fields appropriately)
- [ ] **Consider denormalization**: For frequently accessed data, consider appropriate denormalization

## Code Readability and Maintainability

- [x] **Break down functions**: Split large functions like `process_openalex_works` into smaller, single-responsibility functions within the `OpenAlexProcessor` class

  Implementation Notes:
  - The existing procedural functions have been refactored into a class with focused methods
  - Usage pattern: Replace all calls to `process_openalex_works(works)` with:
    ```python
    processor = OpenAlexProcessor()
    processor.process_works(works)
    ```
  - Update all imports to include `OpenAlexProcessor` alongside the existing functions

- [x] **Add comprehensive documentation**: Document the purpose and behavior of each function with clear docstrings

  Implementation Notes:
  - Added docstrings to all methods explaining their purpose, parameters, and return values
  - Documented key processes within each method using inline comments
  - Added type hints to method signatures to improve code understanding

- [x] **Create a processing pipeline**: Refactor into a clear pipeline with distinct stages that can be tested independently

  Implementation Notes:
  - Refactored code into a class-based processor with clear pipeline stages:
    1. Author creation from work authorships
    2. Paper creation/updating
    3. Fetching detailed author information
    4. Merging author data between systems
    5. Creating related objects (tags, authorships, etc.)
  - Each stage is encapsulated in its own method
  - Maintained backward compatibility with wrapper function

- [x] **Improve variable naming**: Use more descriptive variable names that indicate purpose (e.g., `papers_to_process` instead of `works`)

  Implementation Notes:
  - Changed `works` to `openalex_works` to clearly indicate data source
  - Renamed `fetched_oa_authors` to `detailed_author_data` to better reflect content
  - Updated dictionary names to be more descriptive of their purpose:
    - `authors_by_oa_id` → `researchhub_authors_by_openalex_id`
    - `oa_authors_by_work_id` → `openalex_authors_by_work_id`

- [x] **Add type hints**: Add comprehensive type annotations to improve code understanding and enable static analysis

  Implementation Notes:
  - Added return type annotations to key methods
  - Added proper type hints for complex data structures using Dict, List, and Any
  - Used more specific types where appropriate (e.g., Author instead of Any)

- [x] **Improve code organization**: Move utility methods to appropriate locations in the codebase

  Implementation Notes:
  - Moved URL cleaning function from OpenAlexProcessor to utils/http.py
  - Created a well-documented, general-purpose clean_url function
  - Updated OpenAlexProcessor to use the utility function instead
  - Removed redundant utility code from processor class

- [x] **Separate API interaction code**: Move OpenAlex API interaction code to a dedicated service class

  Implementation Notes:
  - Created a new `OpenAlexService` class in `utils/openalex_service.py`
  - Added caching to reduce redundant API calls
  - Improved error handling for API interactions
  - Encapsulated all external API interactions in one place
  - Updated `OpenAlexProcessor` to use the service instead of direct API calls

- [ ] **Create data transfer objects**: Use dataclasses or Pydantic models to represent OpenAlex data structures
- [ ] **Add more error handling**: Implement more robust error handling with specific exception types
- [ ] **Write unit tests**: Add comprehensive unit tests to ensure functionality and enable safe refactoring
- [ ] **Implement dependency injection**: Refactor to allow injecting dependencies like the OpenAlex client for easier testing
