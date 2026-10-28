from django.db import models

class AIProcessingJob(models.Model):
    PENDING, RUNNING, READY, FAILED, CANCELED = 'PENDING', 'RUNNING', 'READY', 'FAILED', 'CANCELED'
    STATUS_CHOICES = [(value, value) for value in (PENDING, RUNNING, READY, FAILED, CANCELED)]
    file_version = models.ForeignKey('files.FileVersion', on_delete=models.CASCADE, related_name='ai_jobs')
    config_key = models.CharField(max_length=64)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    manual_retries = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=40, blank=True)
    queued_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=32, blank=True)
    content_hash = models.CharField(max_length=64)
    split_revision = models.CharField(max_length=40)
    embedding_provider = models.CharField(max_length=30)
    embedding_model = models.CharField(max_length=100)
    embedding_dimension = models.PositiveIntegerField()
    embedding_tokens = models.PositiveIntegerField(default=0)
    index_revision = models.CharField(max_length=40)
    collection_name = models.CharField(max_length=100)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['file_version', 'config_key'], name='unique_ai_job_config')]

class DocumentChunk(models.Model):
    job = models.ForeignKey(AIProcessingJob, on_delete=models.CASCADE, related_name='chunks')
    file_version = models.ForeignKey('files.FileVersion', on_delete=models.CASCADE)
    ordinal = models.PositiveIntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    heading = models.CharField(max_length=255, blank=True)
    paragraph_number = models.PositiveIntegerField()
    char_start = models.PositiveIntegerField()
    char_end = models.PositiveIntegerField()
    point_id = models.UUIDField(unique=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['job', 'ordinal'], name='unique_ai_job_chunk')]

class ActiveIndex(models.Model):
    file = models.OneToOneField('files.File', on_delete=models.CASCADE, related_name='active_index')
    job = models.ForeignKey(AIProcessingJob, on_delete=models.CASCADE)
    activated_at = models.DateTimeField(auto_now=True)


class Question(models.Model):
    QUEUED, GENERATING, COMPLETED, FAILED = 'QUEUED', 'GENERATING', 'COMPLETED', 'FAILED'
    STATUSES = [(value, value) for value in (QUEUED, GENERATING, COMPLETED, FAILED)]
    ANSWER_STATUSES = [('answered', 'answered'), ('insufficient_evidence', 'insufficient_evidence')]
    group = models.ForeignKey('groups.Group', on_delete=models.CASCADE)
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    question = models.TextField()
    request_key = models.CharField(max_length=80, null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUSES, default=QUEUED)
    answer_status = models.CharField(max_length=24, choices=ANSWER_STATUSES, blank=True)
    answer = models.TextField(blank=True)
    model = models.CharField(max_length=100)
    provider_kind = models.CharField(max_length=20, default='fake')
    prompt_revision = models.CharField(max_length=40)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    duration_ms = models.PositiveIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=40, blank=True)
    lease_token = models.CharField(max_length=32, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['group', 'user', 'request_key'], name='unique_question_request_key')]


class AnswerCitation(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='citations')
    chunk = models.ForeignKey(DocumentChunk, on_delete=models.PROTECT)
    file_version = models.ForeignKey('files.FileVersion', on_delete=models.PROTECT)
    quote = models.TextField()
    ordinal = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['question', 'ordinal'], name='unique_answer_citation_ordinal')]


class QuestionFeedback(models.Model):
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name='feedback')
    user = models.ForeignKey('users.User', on_delete=models.CASCADE)
    rating = models.SmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
