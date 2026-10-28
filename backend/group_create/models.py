from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Document(models.Model):
    name = models.CharField(max_length=255)
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    version = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} v{self.version}"

class Group(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)  # ✅ 추가
    invite_code = models.CharField(max_length=8, blank=True, null=True)  # ✅ 추가
    
     
    def __str__(self):
        return self.name