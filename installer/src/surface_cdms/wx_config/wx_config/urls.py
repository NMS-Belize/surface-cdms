"""wx_config URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from config_app import views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.index, name='wx_configuration'),
    path('install-surface/', include('surface_app.urls')),
    path('terminate-task/<celery_task_id>/', views.terminate_task, name='terminate_task_by_id'),
    path('shutdown/', views.shutdown, name='shutdown'),
]
