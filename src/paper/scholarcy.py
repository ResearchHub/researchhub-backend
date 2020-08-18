import requests


class ScholarcyMetadata:
    base_url = 'https://api.scholarcy.com/api/'
    options = {
        'generate_summary': True,
        'extract_claims': True,
    }

    def __init__(self, url, options={}):
        self.url = url
        self.request_url = f'{self.base_url}metadata/extract'
        self.options['url'] = url
        self.options.update(options)

        response = requests.post(self.request_url, data=self.options)
        if response.status_code != 200:
            raise Exception(response.text)

        self.data = response.json()
        if self.data.get('content_type') is None:
            raise Exception('Error: Could not find pdf')

    def get_summary(self):
        summary = self.data.get('summary')
        summary_text = ''.join(summary)
        return summary_text

    def get_key_takeaways(self):
        takeaways = self.data.get('top_statements')
        return takeaways

    def get_references(self):
        references = self.data.get('reference_links')
        return references

    def get_figures(self, include_captions=True):
        captions = []
        if include_captions:
            captions = self.data.get('figure_captions')
        figures = self.data.get('figure_urls')
        return figures, captions
