"""
PubMed API response fixtures for testing
"""

import json

# Sample PubMed ESearch response
PUBMED_ESEARCH_RESPONSE = {
    "header": {"type": "esearch", "version": "0.3"},
    "esearchresult": {
        "count": "3",
        "retmax": "3",
        "retstart": "0",
        "idlist": ["38234567", "38234568", "38234569"],
        "translationset": [],
        "querytranslation": '("last_7_days"[CRDT] OR "last_7_days"[EDAT]) AND (preprint[pt])',
        "webenv": "MCID_65a1234567890abcdef12345",
        "querykey": "1",
    },
}

# Sample PubMed EFetch response (XML format)
PUBMED_EFETCH_RESPONSE = """<?xml version="1.0"?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN" "https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_240101.dtd">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="PubMed-not-MEDLINE" Owner="NLM">
      <PMID Version="1">38234567</PMID>
      <DateCompleted>
        <Year>2024</Year>
        <Month>01</Month>
        <Day>15</Day>
      </DateCompleted>
      <Article PubModel="Electronic">
        <Journal>
          <ISSN IssnType="Electronic">1234-5678</ISSN>
          <JournalIssue CitedMedium="Internet">
            <Volume>15</Volume>
            <Issue>1</Issue>
            <PubDate>
              <Year>2024</Year>
              <Month>Jan</Month>
              <Day>10</Day>
            </PubDate>
          </JournalIssue>
          <Title>Nature Medicine</Title>
          <ISOAbbreviation>Nat Med</ISOAbbreviation>
        </Journal>
        <ArticleTitle>Novel therapeutic approach for Alzheimer's disease using targeted gene therapy</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND" NlmCategory="BACKGROUND">Alzheimer's disease (AD) is a devastating neurodegenerative disorder affecting millions worldwide. Current treatments provide only symptomatic relief.</AbstractText>
          <AbstractText Label="METHODS" NlmCategory="METHODS">We developed a novel AAV-based gene therapy targeting amyloid-beta production. The therapy was tested in transgenic mouse models and non-human primates.</AbstractText>
          <AbstractText Label="RESULTS" NlmCategory="RESULTS">Treatment resulted in 70% reduction in amyloid plaque burden and significant improvement in cognitive function. No adverse effects were observed.</AbstractText>
          <AbstractText Label="CONCLUSIONS" NlmCategory="CONCLUSIONS">This gene therapy approach shows promise for treating AD and warrants clinical trials.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Johnson</LastName>
            <ForeName>Emily R</ForeName>
            <Initials>ER</Initials>
            <AffiliationInfo>
              <Affiliation>Department of Neurology, Harvard Medical School, Boston, MA, USA.</Affiliation>
            </AffiliationInfo>
            <Identifier Source="ORCID">0000-0001-2345-6789</Identifier>
          </Author>
          <Author ValidYN="Y">
            <LastName>Wang</LastName>
            <ForeName>Li</ForeName>
            <Initials>L</Initials>
            <AffiliationInfo>
              <Affiliation>Broad Institute of MIT and Harvard, Cambridge, MA, USA.</Affiliation>
            </AffiliationInfo>
          </Author>
          <Author ValidYN="Y">
            <LastName>Smith</LastName>
            <ForeName>Michael D</ForeName>
            <Initials>MD</Initials>
            <AffiliationInfo>
              <Affiliation>Department of Genetics, Stanford University, Stanford, CA, USA.</Affiliation>
            </AffiliationInfo>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
          <PublicationType UI="D000076942">Preprint</PublicationType>
        </PublicationTypeList>
        <ArticleDate DateType="Electronic">
          <Year>2024</Year>
          <Month>01</Month>
          <Day>10</Day>
        </ArticleDate>
      </Article>
      <MedlineJournalInfo>
        <Country>United States</Country>
        <MedlineTA>Nat Med</MedlineTA>
        <NlmUniqueID>9876543</NlmUniqueID>
        <ISSNLinking>1234-5678</ISSNLinking>
      </MedlineJournalInfo>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D000544" MajorTopicYN="Y">Alzheimer Disease</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D015316" MajorTopicYN="Y">Genetic Therapy</DescriptorName>
        </MeshHeading>
        <MeshHeading>
          <DescriptorName UI="D016229" MajorTopicYN="N">Amyloid beta-Peptides</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38234567</ArticleId>
        <ArticleId IdType="doi">10.1038/s41591-024-01234</ArticleId>
        <ArticleId IdType="pmc">PMC10987654</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation Status="Publisher" Owner="NLM">
      <PMID Version="1">38234568</PMID>
      <Article PubModel="Print-Electronic">
        <Journal>
          <Title>Cell</Title>
        </Journal>
        <ArticleTitle>Structural basis of SARS-CoV-2 variant immune escape mechanisms</ArticleTitle>
        <Abstract>
          <AbstractText>We present cryo-EM structures of SARS-CoV-2 Omicron variant spike protein complexed with neutralizing antibodies. These structures reveal mechanisms of immune escape and inform vaccine design strategies.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Chen</LastName>
            <ForeName>Wei</ForeName>
            <Initials>W</Initials>
          </Author>
          <Author ValidYN="Y">
            <LastName>Roberts</LastName>
            <ForeName>Sarah K</ForeName>
            <Initials>SK</Initials>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
        </PublicationTypeList>
        <ArticleDate DateType="Electronic">
          <Year>2024</Year>
          <Month>01</Month>
          <Day>12</Day>
        </ArticleDate>
        <ELocationID EIdType="doi" ValidYN="Y">10.1016/j.cell.2024.01.001</ELocationID>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38234568</ArticleId>
        <ArticleId IdType="doi">10.1016/j.cell.2024.01.001</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

# Empty PubMed search response
PUBMED_EMPTY_SEARCH = {
    "header": {"type": "esearch", "version": "0.3"},
    "esearchresult": {
        "count": "0",
        "retmax": "0",
        "retstart": "0",
        "idlist": [],
        "translationset": [],
        "querytranslation": "nonexistent_query[ti]",
    },
}

# PubMed EFetch with PMC article
PUBMED_PMC_RESPONSE = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation Status="PubMed" Owner="NLM">
      <PMID Version="1">38234569</PMID>
      <Article>
        <ArticleTitle>Open access article with PMC full text</ArticleTitle>
        <Abstract>
          <AbstractText>This is an open access article available in PMC.</AbstractText>
        </Abstract>
        <AuthorList CompleteYN="Y">
          <Author ValidYN="Y">
            <LastName>Doe</LastName>
            <ForeName>Jane</ForeName>
            <Initials>J</Initials>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
        </PublicationTypeList>
        <ArticleDate DateType="Electronic">
          <Year>2024</Year>
          <Month>01</Month>
          <Day>05</Day>
        </ArticleDate>
        <ELocationID EIdType="doi" ValidYN="Y">10.1371/journal.pone.0123456</ELocationID>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">38234569</ArticleId>
        <ArticleId IdType="doi">10.1371/journal.pone.0123456</ArticleId>
        <ArticleId IdType="pmc">PMC10987655</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>"""

# Convert to JSON strings where needed
PUBMED_ESEARCH_RESPONSE_JSON = json.dumps(PUBMED_ESEARCH_RESPONSE)
