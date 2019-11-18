# TODO: This is WIP and needs to be finished and tested

# from django.core.management.base import BaseCommand, CommandError

# from search.plugins import pdf_pipeline


# class Command(BaseCommand):

#     def add_arguments(self, parser):
#         parser.add_arguments('-paper_ids', nargs='+', type=int)
#         parser.add_arguments('--destory')

#     def handle(self, *args, **options):
#         paper_ids = options['paper_ids']

#         if options['destroy']:
#             response = pdf_pipeline.delete()
#             print('OK', response.ok)

#         elif paper_ids is not None:
#             for paper_id in paper_ids:
#                 pdf_pipeline.attach_paper_pdf_by_id(paper_id)
#         else:
#             pdf_pipeline.attach_all()

#         print('DONE')
