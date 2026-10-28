from celery import shared_task
from .services import process_job

@shared_task(name='ai_assistant.process_document', soft_time_limit=120, time_limit=150, acks_late=True)
def process_document(job_id):
    process_job(job_id)


@shared_task(name='ai_assistant.answer_question', soft_time_limit=60, time_limit=70, acks_late=True)
def answer_question(question_id):
    from .answers import process_question
    process_question(question_id)
