from django.urls import path
from .web_views import web_login, web_signup, web_logout, web_home, web_group, web_file, web_ask

urlpatterns = [
    path('login/', web_login, name='web-login'),
    path('signup/', web_signup, name='web-signup'),
    path('logout/', web_logout, name='web-logout'),
    path('', web_home, name='web-home'),
    path('groups/<int:group_id>/', web_group, name='web-group'),
    path('groups/<int:group_id>/ask/', web_ask, name='web-ask'),
    path('groups/<int:group_id>/files/<int:file_id>/', web_file, name='web-file'),
]
