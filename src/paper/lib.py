import utils.sentry as sentry

from utils.http import check_url_contains_pdf

# TODO: Create classes of url patterns to generalize this even further esp for
# subdomains.


class Journal:
    """
    Subclasses must define all attributes.
    """
    host = None
    journal_url_base = None
    journal_url_split_on = None
    pdf_url_base = None
    pdf_url_split_on = None
    pdf_url_suffix = None

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        raise NotImplementedError

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        raise NotImplementedError

    @classmethod
    def remove_query(cls, string):
        parts = string.split('?')
        return parts[0]


class Arxiv(Journal):
    host = 'arxiv.org'
    journal_url_base = 'https://arxiv.org/abs/'
    journal_url_split_on = 'arxiv.org/abs/'
    pdf_url_base = 'https://arxiv.org/pdf/'
    pdf_url_split_on = 'arxiv.org/pdf/'
    pdf_url_suffix = '.pdf'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on)
        try:
            uid_parts = parts[1].split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            uid = cls.remove_query(uid)
            return f'{cls.journal_url_base}{uid}'
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class Biorxiv(Journal):
    host = 'biorxiv.org'
    journal_url_base = 'https://www.biorxiv.org/content/'
    journal_url_split_on = 'biorxiv.org/content/'
    pdf_url_base = 'https://www.biorxiv.org/content/'
    pdf_url_split_on = 'biorxiv.org/content/'
    pdf_url_suffix = '.full.pdf'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on)
        try:
            uid_parts = cls.remove_query(parts[1]).split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            return f'{cls.journal_url_base}{uid}'
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class Nature(Journal):
    host = 'nature.com'
    journal_url_base = 'https://www.nature.com/articles/'
    journal_url_split_on = 'nature.com/articles/'
    pdf_url_base = 'https://www.nature.com/articles/'
    pdf_url_split_on = 'nature.com/articles/'
    pdf_url_suffix = '.pdf'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'

            if check_url_contains_pdf(pdf_url):
                return pdf_url
            return None
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on)
        try:
            uid_parts = cls.remove_query(parts[1]).split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            return f'{cls.journal_url_base}{uid}'
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class JNeurosci(Journal):
    host = 'jneurosci.org'
    journal_url_base = 'https://www.jneurosci.org/content/'
    journal_url_split_on = 'jneurosci.org/content/'
    pdf_url_base = 'https://www.jneurosci.org/content/jneuro/'
    pdf_url_split_on = 'jneurosci.org/content/jneuro/'
    pdf_url_suffix = '.full.pdf'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_suffix)
        try:
            uid_parts = cls.remove_query(parts[0]).split(cls.pdf_url_suffix)
            uid = uid_parts[0].split(cls.pdf_url_split_on)[1]
            journal_url = f'{cls.journal_url_base}{uid}'
            return journal_url
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class PLOS(Journal):
    host = 'journals.plos.org'
    journal_url_base = 'https://journals.plos.org/plosone/article?'
    journal_url_split_on = 'journals.plos.org/plosone/article?'
    pdf_url_base = 'https://journals.plos.org/plosone/article/file?'
    pdf_url_split_on_partial = 'journals.plos.org/plosone/article/file?'
    pdf_url_suffix = '&type=printable'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on_partial)
        try:
            uid_parts = cls.remove_query(parts[1]).split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            journal_url = f'{cls.journal_url_base}{uid}'
            return journal_url
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class PNAS(Journal):
    host = 'pnas.org'
    journal_url_base = 'https://www.pnas.org/content/'
    journal_url_split_on = 'pnas.org/content/'
    pdf_url_base = 'https://www.pnas.org/content/pnas/'
    pdf_url_split_on_partial = 'pnas.org/content/pnas/'
    pdf_url_suffix = '.full.pdf'
    pdf_identifier = pdf_url_suffix

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on_partial)
        try:
            uid_parts = cls.remove_query(parts[1]).split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            journal_url = f'{cls.journal_url_base}{uid}'
            return journal_url
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


class Lancet(Journal):
    # Journal id doesn't seem to matter much
    host = 'thelancet.com'
    journal_url_base = 'https://www.thelancet.com/journals/journal_id/article/PII'
    journal_url_split_on = '/article/PII'
    journal_url_suffix = '/fulltext'
    pdf_url_base = 'https://www.thelancet.com/action/showPdf?pii='
    pdf_url_split_on_partial = 'thelancet.com/action/showPdf?pii='
    pdf_url_suffix = ''
    pdf_identifier = 'showPdf?'

    @classmethod
    def journal_url_to_pdf_url(cls, journal_url):
        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1].split(cls.journal_url_suffix)[0]
            uid = cls.remove_query(uid)
            pdf_url = f'{cls.pdf_url_base}{uid}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        parts = pdf_url.split(cls.pdf_url_split_on_partial)
        try:
            uid = cls.remove_query(parts[1])
            journal_url = f'{cls.journal_url_base}{uid}{cls.journal_url_suffix}'
            return journal_url
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None


SUB_KEYS = {
    'advances': 'advances',
    'jpet': 'jpet'
}


class JournalWithSubdomain:
    """
    Subclasses must define all attributes.
    """
    host = None
    journal_url_split_on = None
    pdf_url_split_on_partial = None
    pdf_url_suffix = None

    @classmethod
    def remove_query(cls, string):
        parts = string.split('?')
        return parts[0]

    def journal_url_to_pdf_url(cls, journal_url):
        subdomain = cls.get_subdomain(journal_url)
        try:
            sub_key = SUB_KEYS[subdomain]
        except KeyError:
            sub_key = subdomain

        parts = journal_url.split(cls.journal_url_split_on)
        try:
            uid = parts[1]
            uid = cls.remove_query(uid)
            pdf_url_base = cls.build_pdf_url_base(subdomain, sub_key)
            pdf_url = f'{pdf_url_base}{uid}{cls.pdf_url_suffix}'
            return pdf_url
        except Exception as e:
            sentry.log_error(e, message=journal_url)
            return None

    @classmethod
    def pdf_url_to_journal_url(cls, pdf_url):
        subdomain = cls.get_subdomain(pdf_url)
        try:
            sub_key = SUB_KEYS[subdomain]
        except KeyError:
            sub_key = subdomain

        pdf_url_split_on = cls.build_pdf_url_split_on(sub_key)
        parts = pdf_url.split(pdf_url_split_on)
        try:
            uid_parts = cls.remove_query(parts[1]).split(cls.pdf_url_suffix)
            uid = uid_parts[0]
            journal_url_base = cls.build_journal_url_base(subdomain)
            journal_url = f'{journal_url_base}{uid}'
            return journal_url
        except Exception as e:
            sentry.log_error(e, message=pdf_url)
            return None

    @classmethod
    def get_subdomain(cls, url):
        parts = url.split('.' + cls.host)
        if len(parts) > 1:
            sub_parts = parts[0].split('://')
            if len(sub_parts) > 1:
                return sub_parts[1]
        return ''

    @classmethod
    def build_pdf_url_split_on(cls, sub_key):
        return f'{cls.pdf_url_split_on_partial}{sub_key}/'

    @classmethod
    def build_journal_url_base(cls, subdomain):
        return f'https://{subdomain}.{cls.host}/content/'

    @classmethod
    def build_pdf_url_base(cls, subdomain, sub_key):
        return f'https://{subdomain}.{cls.host}/content/{sub_key}/'


class ScienceMag(JournalWithSubdomain):
    host = 'sciencemag.org'
    journal_url_split_on = 'sciencemag.org/content/'
    pdf_url_split_on_partial = 'sciencemag.org/content/'
    pdf_url_suffix = '.full.pdf'
    pdf_identifier = pdf_url_suffix


class JPET_ASPET(JournalWithSubdomain):
    host = 'aspetjournals.org'
    journal_url_split_on = 'jpet.aspetjournals.org/content/'
    pdf_url_split_on_partial = 'jpet.aspetjournals.org/content/'
    pdf_url_suffix = '.full.pdf'
    pdf_identifier = pdf_url_suffix


journal_hosts = [
    Arxiv.host,
    Biorxiv.host,
    ScienceMag.host,
    Nature.host,
    JNeurosci.host,
    PLOS.host,
    PNAS.host,
    Lancet.host,
    JPET_ASPET.host
]

pdf_identifiers = [
    Arxiv.pdf_identifier,
    Biorxiv.pdf_identifier,
    ScienceMag.pdf_identifier,
    Nature.pdf_identifier,
    JNeurosci.pdf_identifier,
    PLOS.pdf_identifier,
    PNAS.pdf_identifier,
    Lancet.pdf_identifier,
    JPET_ASPET.pdf_identifier,
]

journal_hosts_and_pdf_identifiers = [
    (Arxiv.host, Arxiv.pdf_identifier),
    (Biorxiv.host, Biorxiv.pdf_identifier),
    (ScienceMag.host, ScienceMag.pdf_identifier),
    (Nature.host, Nature.pdf_identifier),
    (JNeurosci.host, JNeurosci.pdf_identifier),
    (PLOS.host, PLOS.pdf_identifier),
    (PNAS.host, PNAS.pdf_identifier),
    (Lancet.host, Lancet.pdf_identifier),
    (JPET_ASPET.host, JPET_ASPET.pdf_identifier),
]

journal_pdf_to_url = {
    Arxiv.host: Arxiv.pdf_url_to_journal_url,
    Biorxiv.host: Biorxiv.pdf_url_to_journal_url,
    Nature.host: Nature.pdf_url_to_journal_url,
    JNeurosci.host: JNeurosci.pdf_url_to_journal_url,
    PLOS.host: PLOS.pdf_url_to_journal_url,
    PNAS.host: PNAS.pdf_url_to_journal_url,
    Lancet.host: Lancet.pdf_url_to_journal_url,

    # Sites with subdomains
    ScienceMag.host: ScienceMag().pdf_url_to_journal_url,
    JPET_ASPET.host: JPET_ASPET().pdf_url_to_journal_url
}

journal_url_to_pdf = {
    Arxiv.host: Arxiv.journal_url_to_pdf_url,
    Biorxiv.host: Biorxiv.journal_url_to_pdf_url,
    Nature.host: Nature.journal_url_to_pdf_url,
    JNeurosci.host: JNeurosci.journal_url_to_pdf_url,
    PLOS.host: PLOS.journal_url_to_pdf_url,
    PNAS.host: PNAS.journal_url_to_pdf_url,
    Lancet.host: Lancet.journal_url_to_pdf_url,

    # Sites with subdomains
    ScienceMag.host: ScienceMag().journal_url_to_pdf_url,
    JPET_ASPET.host: JPET_ASPET().journal_url_to_pdf_url
}
