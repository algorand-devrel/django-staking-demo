from django.shortcuts import render
from django.http import HttpResponse

from algosdk import v2client

algod_token   = 'a' * 64
algod_address = 'http://192.168.1.142:4001'
algod_client  = v2client.algod.AlgodClient(algod_token, algod_address)

# Create your views here.
def index(request):
    return render(request, 'staking/index.html')
#    return HttpResponse("Hello, World!")

def test_template(request):
    status = algod_client.status()
    last_round = status['last-round']
    return render(request, 'staking/staking.html', {'status': status})

