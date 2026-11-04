from django.urls import path
from . import views

urlpatterns = [
    path("add/", views.add_server, name="add"),
    path("ports/", views.free_ports, name="ports"),
    path("racks/", views.racks, name="racks"),
]
