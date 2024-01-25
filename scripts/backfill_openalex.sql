-- Make backups of the tables
CREATE TABLE paper_paper_backup AS TABLE paper_paper;
CREATE TABLE researchhub_document_researchhubunifieddocument_backup AS TABLE researchhub_document_researchhubunifieddocument;
CREATE TABLE researchhub_document_unifieddocumentconcepts_backup AS TABLE researchhub_document_unifieddocumentconcepts;
CREATE TABLE researchhub_document_researchhubunifieddocument_hubs_backup AS TABLE researchhub_document_researchhubunifieddocument_hubs;

-- Create temp tables
CREATE TABLE backfill_paper_paper (
  title character varying(1024),
  paper_publish_date date,
  doi character varying(255),
  url character varying(1024),
  publication_type character varying(255),
  paper_title character varying(1024),
  pdf_url character varying(2048),
  retrieved_from_external_source boolean NOT NULL,
  is_public boolean NOT NULL,
  is_removed boolean NOT NULL,
  external_source character varying(255),
  pdf_license character varying(255),
  raw_authors jsonb,
  discussion_count integer NOT NULL,
  alternate_ids jsonb NOT NULL,
  slug character varying(1024),
  alt_slug character varying(1024),
  paper_type character varying(32) NOT NULL,
  completeness character varying(16) NOT NULL,
  open_alex_raw_json jsonb,
  citations integer NOT NULL,
  downloads integer NOT NULL,
  twitter_mentions integer NOT NULL,
  views integer NOT NULL,
  is_open_access boolean,
  oa_status character varying(8)
);
CREATE TABLE backfill_researchhub_unified_document (
  document_type character varying(32) NOT NULL,
  published_date date NOT NULL,
  paper_doi character varying(255),
  paper_url character varying(1024)
);
CREATE TABLE backfill_tag_concept (
  openalex_id character varying(255),
  display_name character varying(255),
  level integer,
  score double precision,
  paper_doi character varying(255),
  paper_url character varying(1024)
);

-- Load data from CSVs
\copy backfill_paper_paper FROM '~/openalex-snapshot/2023/2023_paper_paper_part1.csv' DELIMITER ',' CSV HEADER; 
\copy backfill_researchhub_unified_document FROM '~/openalex-snapshot/2023/2023_researchhub_unified_document_part1.csv' DELIMITER ',' CSV HEADER;
\copy backfill_tag_concept FROM '~/openalex-snapshot/2023/2023_tag_concept_part1.csv' DELIMITER ',' CSV HEADER;

-- Remove duplicates/invalid
-- add idx first
CREATE INDEX idx_backfill_paper_doi ON backfill_paper_paper(doi);
-- this is an optimized delete
WITH duplicate_rows AS (
    SELECT ctid
    FROM (
        SELECT ctid, 
               row_number() OVER (PARTITION BY doi ORDER BY ctid) as rn
        FROM backfill_paper_paper
    ) t
    WHERE rn > 1
)
DELETE FROM backfill_paper_paper
WHERE ctid IN (SELECT ctid FROM duplicate_rows);
-- delete duplicate rows by url
CREATE INDEX idx_backfill_paper_url ON backfill_paper_paper(url);
WITH duplicate_rows AS (
    SELECT ctid
    FROM (
        SELECT ctid, 
               row_number() OVER (PARTITION BY url ORDER BY ctid) as rn
        FROM backfill_paper_paper
    ) t
    WHERE rn > 1
)
DELETE FROM backfill_paper_paper
WHERE ctid IN (SELECT ctid FROM duplicate_rows);
-- delete invalid rows
DELETE FROM backfill_paper_paper
WHERE doi IS NULL OR doi = '' OR title IS NULL OR title = '' OR slug IS NULL OR slug = '' OR url IS NULL OR url = '';
-- Truncate url to 1024 characters (there's some with more)
SELECT id FROM backfill_paper_paper WHERE LENGTH(pdf_url) > 1024;
ALTER TABLE backfill_paper_paper ALTER COLUMN pdf_url TYPE character varying(1024);
-- add serial id
ALTER TABLE backfill_paper_paper
ADD COLUMN id SERIAL PRIMARY KEY;


-- Insert or Update in the main table
INSERT INTO paper_paper (
  title, paper_publish_date, doi, url, publication_type, paper_title, pdf_url,
  retrieved_from_external_source, is_public, is_removed, external_source,
  pdf_license, raw_authors, discussion_count, alternate_ids, slug,
  paper_type, completeness, open_alex_raw_json, citations, downloads,
  twitter_mentions, views, is_open_access, oa_status, created_date, updated_date,
  is_removed_by_user, bullet_low_quality, summary_low_quality,
  automated_bounty_created, is_pdf_removed_by_moderator, twitter_score, score
)
SELECT title, paper_publish_date, doi, url, publication_type, paper_title, pdf_url,
  retrieved_from_external_source, is_public, is_removed, external_source,
  pdf_license, raw_authors, discussion_count, alternate_ids, slug,
  paper_type, completeness, open_alex_raw_json, citations, downloads,
  twitter_mentions, views, is_open_access, oa_status, NOW(), NOW(), false,
  false, false, false, false, 0, 0
FROM backfill_paper_paper b
WHERE NOT EXISTS (
    SELECT 1 FROM paper_paper p WHERE p.url = b.url
)
ON CONFLICT (doi)
DO UPDATE SET
  paper_publish_date = excluded.paper_publish_date,
  pdf_license = excluded.pdf_license,
  alternate_ids = excluded.alternate_ids,
  citations = excluded.citations,
  is_open_access = excluded.is_open_access,
  oa_status = excluded.oa_status,
  open_alex_raw_json = excluded.open_alex_raw_json,
  updated_date = NOW()
WHERE paper_paper.paper_publish_date IS DISTINCT FROM excluded.paper_publish_date
   OR paper_paper.pdf_license IS DISTINCT FROM excluded.pdf_license
   OR paper_paper.alternate_ids IS DISTINCT FROM excluded.alternate_ids
   OR paper_paper.citations IS DISTINCT FROM excluded.citations
   OR paper_paper.is_open_access IS DISTINCT FROM excluded.is_open_access
   OR paper_paper.oa_status IS DISTINCT FROM excluded.oa_status
   OR paper_paper.open_alex_raw_json IS DISTINCT FROM excluded.open_alex_raw_json;
-- batched version
DO $$
DECLARE
    batch_size int := 5000;
    offset_val int := 0;
    rows_affected int;
BEGIN
    LOOP
        INSERT INTO paper_paper (
          title, paper_publish_date, doi, url, publication_type, paper_title, pdf_url,
          retrieved_from_external_source, is_public, is_removed, external_source,
          pdf_license, raw_authors, discussion_count, alternate_ids, slug,
          paper_type, completeness, open_alex_raw_json, citations, downloads,
          twitter_mentions, views, is_open_access, oa_status, created_date, updated_date,
          is_removed_by_user, bullet_low_quality, summary_low_quality,
          automated_bounty_created, is_pdf_removed_by_moderator, twitter_score, score
        )
        SELECT 
          title, paper_publish_date, doi, url, publication_type, paper_title, pdf_url,
          retrieved_from_external_source, is_public, is_removed, external_source,
          pdf_license, raw_authors, discussion_count, alternate_ids, slug,
          paper_type, completeness, open_alex_raw_json, citations, downloads,
          twitter_mentions, views, is_open_access, oa_status, NOW(), NOW(), false,
          false, false, false, false, 0, 0
        FROM backfill_paper_paper b
        WHERE NOT EXISTS (
            SELECT 1 FROM paper_paper p WHERE p.url = b.url
        )
        ORDER BY b.id
        LIMIT batch_size OFFSET offset_val
        ON CONFLICT (doi) DO UPDATE SET
          paper_publish_date = excluded.paper_publish_date,
          pdf_license = excluded.pdf_license,
          alternate_ids = excluded.alternate_ids,
          citations = excluded.citations,
          is_open_access = excluded.is_open_access,
          oa_status = excluded.oa_status,
          open_alex_raw_json = excluded.open_alex_raw_json,
          updated_date = NOW()
        WHERE paper_paper.paper_publish_date IS DISTINCT FROM excluded.paper_publish_date
          OR paper_paper.pdf_license IS DISTINCT FROM excluded.pdf_license
          OR paper_paper.alternate_ids IS DISTINCT FROM excluded.alternate_ids
          OR paper_paper.citations IS DISTINCT FROM excluded.citations
          OR paper_paper.is_open_access IS DISTINCT FROM excluded.is_open_access
          OR paper_paper.oa_status IS DISTINCT FROM excluded.oa_status
          OR paper_paper.open_alex_raw_json IS DISTINCT FROM excluded.open_alex_raw_json;

        GET DIAGNOSTICS rows_affected = ROW_COUNT;
        EXIT WHEN rows_affected < batch_size;
        offset_val := offset_val + batch_size;

        RAISE NOTICE 'Offset: %', offset_val;
        RAISE NOTICE 'Rows affected: %', rows_affected;
    END LOOP;
END $$;

ALTER TABLE backfill_researchhub_unified_document
ADD COLUMN new_unified_document_id INTEGER;

-- Temporarily add a column to unified doc table
ALTER TABLE researchhub_document_researchhubunifieddocument
ADD COLUMN paper_doi character varying(255);

-- Add indexes
CREATE INDEX idx_backfill_researchhub_unified_document_paper_doi ON backfill_researchhub_unified_document(paper_doi);
CREATE INDEX idx_backfill_tag_concept_paper_doi ON backfill_tag_concept(paper_doi);

-- Insert unified documents
-- and update backfill table with new unified_document_id
WITH inserted AS (
  INSERT INTO researchhub_document_researchhubunifieddocument (
    document_type, created_date, updated_date, hot_score, score,
    is_removed, published_date, is_public, hot_score_v2, is_removed_date,
    paper_doi
  )
  SELECT
    b.document_type, NOW(), NOW(), 0, 0,
    false, NOW(), false, 0, NULL, b.paper_doi
  FROM backfill_researchhub_unified_document b
  JOIN paper_paper p ON (b.paper_doi = p.doi OR b.paper_url = p.url)
  WHERE p.unified_document_id IS NULL
  RETURNING id, paper_doi
)
UPDATE backfill_researchhub_unified_document
SET new_unified_document_id = inserted.id
FROM inserted
WHERE backfill_researchhub_unified_document.paper_doi = inserted.paper_doi;

-- let's also update the backfill_tag_concept table with the new unified_document_id
ALTER TABLE backfill_tag_concept
ADD COLUMN new_unified_document_id INTEGER;
-- Set the new unified_document_id to the one we just inserted
UPDATE backfill_tag_concept
SET new_unified_document_id = b.new_unified_document_id
FROM backfill_researchhub_unified_document b
WHERE backfill_tag_concept.paper_doi = b.paper_doi;

-- Update paper_paper table with unified_document_id
UPDATE paper_paper
SET unified_document_id = b.new_unified_document_id
FROM backfill_researchhub_unified_document b
WHERE paper_paper.doi = b.paper_doi AND paper_paper.unified_document_id IS NULL;

-- Insert concepts
INSERT INTO researchhub_document_unifieddocumentconcepts (
  created_date, updated_date, relevancy_score, level, concept_id, unified_document_id
)
SELECT NOW(), NOW(), b.score, b.level, c.id, b.new_unified_document_id
FROM backfill_tag_concept b
JOIN tag_concept c ON b.openalex_id = c.openalex_id
WHERE b.new_unified_document_id IS NOT NULL;

-- Insert hubs
INSERT INTO researchhub_document_researchhubunifieddocument_hubs (
  researchhubunifieddocument_id, hub_id
)
SELECT b.new_unified_document_id, h.id
FROM backfill_tag_concept b
JOIN tag_concept c ON b.openalex_id = c.openalex_id
JOIN hub_hub h ON c.id = h.concept_id
WHERE b.new_unified_document_id IS NOT NULL
ON CONFLICT (researchhubunifieddocument_id, hub_id) 
DO NOTHING;

-- May be useful to run analyze on the tables
ANALYZE paper_paper;
ANALYZE researchhub_document_researchhubunifieddocument;
ANALYZE researchhub_document_unifieddocumentconcepts;
ANALYZE researchhub_document_researchhubunifieddocument_hubs;

-- Cleanup
DROP TABLE backfill_paper_paper;
DROP TABLE backfill_researchhub_unified_document;
DROP TABLE backfill_tag_concept;

ALTER TABLE researchhub_document_researchhubunifieddocument
DROP COLUMN paper_doi;

-- drop backups
DROP TABLE paper_paper_backup;
DROP TABLE researchhub_document_researchhubunifieddocument_backup;
DROP TABLE researchhub_document_unifieddocumentconcepts_backup;
DROP TABLE researchhub_document_researchhubunifieddocument_hubs_backup;
