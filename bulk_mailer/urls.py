from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from mailer_app import views

handler500 = 'mailer_app.views.custom_500'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', auth_views.LoginView.as_view(template_name='mailer_app/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('mailer_app.urls')),
]