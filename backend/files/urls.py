from django.urls import path
from .views import GroupFilesView, GroupFileView, FileVersionsView, VersionDownloadView

urlpatterns = [
    path('<int:group_id>/files/', GroupFilesView.as_view()),
    path('<int:group_id>/files/<int:file_id>/', GroupFileView.as_view()),
    path('<int:group_id>/files/<int:file_id>/versions/', FileVersionsView.as_view()),
    path('<int:group_id>/files/<int:file_id>/versions/<int:version_id>/download/', VersionDownloadView.as_view()),
]
