"""
arXiv API response fixtures for testing
"""

# Sample arXiv API response (Atom feed format)
ARXIV_API_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="http://arxiv.org/api/query?search_query=cat:cs.AI&amp;start=0&amp;max_results=2" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: search_query=cat:cs.AI&amp;start=0&amp;max_results=2</title>
  <id>http://arxiv.org/api/query</id>
  <updated>2024-01-15T00:00:00-04:00</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">50000</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <opensearch:itemsPerPage xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:itemsPerPage>
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <updated>2024-01-01T18:00:00Z</updated>
    <published>2024-01-01T18:00:00Z</published>
    <title>Deep Learning for Natural Language Processing: A Survey</title>
    <summary>We present a comprehensive survey of deep learning techniques for natural language
processing (NLP). This paper reviews the latest advances in neural architectures including
transformers, BERT, GPT, and their variants. We discuss applications in machine translation,
sentiment analysis, question answering, and text generation. Our analysis covers both
theoretical foundations and practical implementations, highlighting key challenges and
future research directions in the field.</summary>
    <author>
      <name>Jane Smith</name>
      <arxiv:affiliation xmlns:arxiv="http://arxiv.org/schemas/atom">Stanford University</arxiv:affiliation>
    </author>
    <author>
      <name>John Doe</name>
      <arxiv:affiliation xmlns:arxiv="http://arxiv.org/schemas/atom">MIT CSAIL</arxiv:affiliation>
    </author>
    <arxiv:doi xmlns:arxiv="http://arxiv.org/schemas/atom">10.1234/arxiv.2401.00001</arxiv:doi>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.00001v1" rel="related" title="pdf" type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <arxiv:comment xmlns:arxiv="http://arxiv.org/schemas/atom">45 pages, 12 figures, accepted to ACL 2024</arxiv:comment>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v2</id>
    <updated>2024-01-05T12:30:00Z</updated>
    <published>2024-01-02T09:15:00Z</published>
    <title>Reinforcement Learning in Robotics: Current State and Future Directions</title>
    <summary>This paper provides an extensive review of reinforcement learning (RL) applications
in robotics. We examine recent breakthroughs in sim-to-real transfer, model-based RL,
and multi-agent coordination. Special attention is given to practical challenges such as
sample efficiency, safety constraints, and real-world deployment. We also discuss emerging
trends including meta-learning, curriculum learning, and human-robot interaction through RL.</summary>
    <author>
      <name>Alice Johnson</name>
      <arxiv:affiliation xmlns:arxiv="http://arxiv.org/schemas/atom">Carnegie Mellon University</arxiv:affiliation>
    </author>
    <author>
      <name>Bob Wilson</name>
    </author>
    <author>
      <name>Carol Martinez</name>
      <arxiv:affiliation xmlns:arxiv="http://arxiv.org/schemas/atom">UC Berkeley</arxiv:affiliation>
    </author>
    <link href="http://arxiv.org/abs/2401.00002v2" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2401.00002v2" rel="related" title="pdf" type="application/pdf"/>
    <arxiv:primary_category xmlns:arxiv="http://arxiv.org/schemas/atom" term="cs.RO" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.RO" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

# Sample OAI-PMH response from arXiv
ARXIV_OAI_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/ http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd">
  <responseDate>2024-01-15T12:00:00Z</responseDate>
  <request verb="ListRecords" from="2024-01-01" until="2024-01-02" metadataPrefix="arXiv">http://export.arxiv.org/oai2</request>
  <ListRecords>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.00003</identifier>
        <datestamp>2024-01-01</datestamp>
        <setSpec>cs</setSpec>
      </header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/"
               xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:schemaLocation="http://arxiv.org/OAI/arXiv/ http://arxiv.org/OAI/arXiv.xsd">
          <id>2401.00003</id>
          <created>2024-01-01</created>
          <updated>2024-01-01</updated>
          <authors>
            <author>
              <keyname>Smith</keyname>
              <forenames>Jane A.</forenames>
            </author>
            <author>
              <keyname>Doe</keyname>
              <forenames>John</forenames>
            </author>
          </authors>
          <title>Quantum Computing for Machine Learning: A Comprehensive Review</title>
          <categories>cs.LG cs.AI quant-ph</categories>
          <comments>30 pages, 8 figures</comments>
          <license>http://creativecommons.org/licenses/by/4.0/</license>
          <abstract>We present a comprehensive review of quantum computing applications in machine learning.
This survey covers quantum algorithms for supervised and unsupervised learning, quantum neural
networks, and quantum optimization techniques. We discuss both theoretical advantages and practical
limitations of current quantum hardware. Special emphasis is placed on near-term applications
using noisy intermediate-scale quantum (NISQ) devices.</abstract>
          <doi>10.1038/s41586-024-00001</doi>
        </arXiv>
      </metadata>
    </record>
    <record>
      <header>
        <identifier>oai:arXiv.org:2401.00004</identifier>
        <datestamp>2024-01-02</datestamp>
        <setSpec>math</setSpec>
      </header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>2401.00004</id>
          <created>2024-01-02</created>
          <authors>
            <author>
              <keyname>Wilson</keyname>
              <forenames>Robert</forenames>
            </author>
          </authors>
          <title>New Results in Algebraic Topology</title>
          <categories>math.AT math.AG</categories>
          <abstract>We prove several new results concerning the homotopy groups of spheres...</abstract>
        </arXiv>
      </metadata>
    </record>
    <resumptionToken cursor="0" completeListSize="150">2024-01-02|1001</resumptionToken>
  </ListRecords>
</OAI-PMH>"""

# Empty response
ARXIV_EMPTY_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link href="http://arxiv.org/api/query?search_query=cat:nonexistent&amp;start=0&amp;max_results=10" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query: search_query=cat:nonexistent&amp;start=0&amp;max_results=10</title>
  <id>http://arxiv.org/api/query</id>
  <updated>2024-01-15T00:00:00-04:00</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:totalResults>
  <opensearch:startIndex xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:startIndex>
  <opensearch:itemsPerPage xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">0</opensearch:itemsPerPage>
</feed>"""

# Error response from OAI-PMH
ARXIV_OAI_ERROR_RESPONSE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2024-01-15T12:00:00Z</responseDate>
  <request verb="ListRecords">http://export.arxiv.org/oai2</request>
  <error code="badArgument">Invalid date format</error>
</OAI-PMH>"""
