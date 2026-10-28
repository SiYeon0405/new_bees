from django.urls import path

from .views import GroupDetailView, GroupJoinView, GroupListCreateView, InviteCreateView

urlpatterns = [
    path('', GroupListCreateView.as_view(), name='group-list-create'),
    path('join/', GroupJoinView.as_view(), name='group-join'),
    path('<int:group_id>/', GroupDetailView.as_view(), name='group-detail'),
    path('<int:group_id>/invites/', InviteCreateView.as_view(), name='group-invite'),
]
