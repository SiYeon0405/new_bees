from django.urls import path
from .views import VersionIndexView, VersionRetryView, QuestionCreateView, QuestionDetailView, QuestionFeedbackView

urlpatterns = [
    path('<int:group_id>/ai/questions/', QuestionCreateView.as_view()),
    path('<int:group_id>/ai/questions/<int:question_id>/', QuestionDetailView.as_view()),
    path('<int:group_id>/ai/questions/<int:question_id>/feedback/', QuestionFeedbackView.as_view()),
    path('<int:group_id>/files/<int:file_id>/versions/<int:version_id>/index/', VersionIndexView.as_view()),
    path('<int:group_id>/files/<int:file_id>/versions/<int:version_id>/index/retry/', VersionRetryView.as_view()),
]
