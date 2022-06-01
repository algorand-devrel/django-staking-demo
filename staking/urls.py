from django.urls import path

from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('pool/<int:pool_id>', views.pool, name='pool'),
    path('<int:pool_id>/deposit', views.deposit, name='deposit'),
    path('<int:pool_id>/withdraw', views.withdraw, name='withdraw'),
    path('<int:pool_id>/claim', views.claim, name='claim'),
    path('submit', views.submit, name='submit'),
    path('new_pool', views.new_pool, name='new_pool'),
    path('create_pool', views.create_pool, name='create_pool'),
    path('init_pool', views.init_pool, name='init_pool'),
    path('new_asset', views.new_asset, name='new_asset'),
    path('create_asset', views.create_asset, name='create_asset'),
]
