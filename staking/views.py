from django.shortcuts import redirect, render
from django.http import HttpResponse, JsonResponse
from django.template import loader
from django.utils.timezone import localtime, now

from algosdk import constants, encoding, logic, v2client
from algosdk.atomic_transaction_composer import AccountTransactionSigner, AtomicTransactionComposer, TransactionWithSigner
from algosdk.abi import Method, Argument, Returns, Contract
from algosdk.future import transaction

import random
import base64
import json
import dateutil.parser
import datetime
import time

# Algod Node Connection Details
algod_token  = 'a' * 64
algod_addr   = 'http://127.0.0.1:4001'
algod_client = v2client.algod.AlgodClient(algod_token, algod_addr)

# Who is the deployer of the staking contracts, this demo assumes a single
# account will be the "author" of the staking pools.
deployer = 'VOMJQOMC262EPYQP2QHMVVGJSGFAJCFBGCVKSSS5I3GDVAOQZ5VN6PBSDE'

# A simple helper function to get the ABI method from the name.
def get_method(c: Contract, name: str) -> Method:
    for m in c.methods:
        if m.name == name:
            return m
    raise Exception("No method with the name {}".format(name))

# Page to list all available staking pools, authored by the deployer address.
def index(request):
    status = algod_client.status()
    last_block = algod_client.block_info(status['last-round'])
    current_time = int(datetime.datetime.fromtimestamp(last_block['block']['ts'] + int(status['time-since-last-round'] / 1000000000)).timestamp())

    acc_apps = algod_client.account_info(deployer)['created-apps']
    pools = []
    for app in acc_apps:
        for gs in app['params']['global-state']:
            match base64.b64decode(gs['key']).decode('utf8'):
                case "SA":
                    app['staking_asset'] = algod_client.asset_info(gs['value']['uint'])
                case "RA":
                    app['reward_asset'] = algod_client.asset_info(gs['value']['uint'])
                case "BT":
                    begin_time = gs['value']['uint']
                case "ET":
                    end_time = gs['value']['uint']
                case "FR":
                    app['rate'] = "%s%%" % (gs['value']['uint'] / 100)

        # Provide a start time if not started, the seconds remaining if
        # in-progress, or "Ended" if finished.
        if begin_time > current_time:
            app['duration'] = datetime.datetime.fromtimestamp(begin_time)
        elif end_time >= current_time:
            app['duration'] = "{} seconds remaining".format(end_time - current_time)
        elif current_time > end_time:
            app['duration'] = 'Ended'

        # Add the pool to be listed on the page.
        pools.append(app)

    template = loader.get_template("staking/index.html")
    context = {
        'pools': pools,
    }
    return HttpResponse(template.render(context, request))

# Display a specific pool and the details associated with it.
def pool(request, pool_id):
    # If a wallet hasn't been selected and set in the cookie, redirect them.
    if 'account' not in request.COOKIES:
        return redirect('/')

    # Retrieve account and pool from the algod node.
    account = request.COOKIES['account']
    pool = algod_client.application_info(pool_id)

    # Fetch additional details from the pool state (e.g. asset details), and
    # convert some values to be more human friendly for the frontend.
    for gs in pool['params']['global-state']:
        match base64.b64decode(gs['key']).decode('utf8'):
            case "SA":
                pool['staked_asset'] = algod_client.asset_info(gs['value']['uint'])
                pool['staked_asset']['params']['unit_name'] = pool['staked_asset']['params']['unit-name']
            case "RA":
                pool['reward_asset'] = algod_client.asset_info(gs['value']['uint'])
                pool['reward_asset']['params']['unit_name'] = pool['reward_asset']['params']['unit-name']
            case "TS":
                pool['total_staked'] = gs['value']['uint']
            case "BT":
                pool['begin_timestamp'] = gs['value']['uint']
                pool['begin_datetime'] = datetime.datetime.fromtimestamp(gs['value']['uint'])
            case "ET":
                pool['end_timestamp'] = gs['value']['uint']
                pool['end_datetime'] = datetime.datetime.fromtimestamp(gs['value']['uint'])
            case "FR":
                pool['basis_points'] = gs['value']['uint']
                pool['rate'] = "%s%%" % (gs['value']['uint'] / 100)

    # Fetch details about the accounts position within the pool.
    acc = algod_client.account_info(account)
    for acc_app in acc['apps-local-state']:
        if acc_app['id'] != pool_id:
            continue
        for ls in acc_app['key-value']:
            match base64.b64decode(ls['key']).decode('utf8'):
                case "AS":
                    pool['user_staked'] = ls['value']['uint']
                    pool['user_staked_raw'] = ls['value']['uint']
                case "AR":
                    pool['user_rewards'] = ls['value']['uint']
                    pool['user_rewards_raw'] = ls['value']['uint']
                case "LU":
                    pool['last_updated'] = ls['value']['uint']
                    pool['last_updated_datetime'] = datetime.datetime.fromtimestamp(ls['value']['uint'])

    # Check some default values are populated if the user hasn't staked in the
    # pool yet. But provide friendlier values in a format a human can read if
    # they have. Arguably this should be done on the frontend.
    if 'total_staked' not in pool:
        pool['total_staked'] = 0
    else:
        pool['total_staked'] = pool['total_staked'] / pow(10, pool['staked_asset']['params']['decimals'])

    if 'user_staked' not in pool:
        pool['user_staked'] = 0
        pool['user_staked_raw'] = 0
    else:
        pool['user_staked'] = pool['user_staked'] / pow(10, pool['staked_asset']['params']['decimals'])

    if 'user_rewards' not in pool:
        pool['user_rewards'] = 0
        pool['user_rewards_raw'] = 0
    else:
        pool['user_rewards'] = pool['user_rewards'] / pow(10, pool['reward_asset']['params']['decimals'])

    if 'rate' not in pool:
        pool['rate'] = 0

    # Calculate the current time of the blockchain.
    status = algod_client.status()
    last_block = algod_client.block_info(status['last-round'])
    current_time = datetime.datetime.fromtimestamp(last_block['block']['ts'] + int(status['time-since-last-round'] / 1000000000))

    # If the staking period has ended, display a different page.
    if pool['end_datetime'] <= current_time:
        template = loader.get_template("staking/pool_ended.html")
    else:
        template = loader.get_template("staking/pool.html")

    context = {
        'pool_id': pool_id,
        'pool_details': pool,
        'current_time': current_time,
    }
    return HttpResponse(template.render(context, request))

# Display a page to create a new ASA.
def new_asset(request):
    # If a wallet hasn't been selected and set in the cookie, redirect them.
    if 'account' not in request.COOKIES:
        return redirect('/')
    template = loader.get_template("staking/new_asset.html")

    # Display all existing assets created by the deployer account.
    acc_assets = algod_client.account_info(deployer)['created-assets']
    assets = []
    for asset in acc_assets:
        asset['params']['unit_name'] = asset['params']['unit-name']
        assets.append(asset)
    context = {
        'assets': assets,
    }
    return HttpResponse(template.render(context, request))

# API: This endpoint is requested via an in-page call.
def create_asset(request):
    data = json.loads(request.body)

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = constants.MIN_TXN_FEE

    # Created a transaction without the use of the ATC here since it's so
    # straight forward and requires no application calls.
    acfg_txn = transaction.AssetCreateTxn(
        data['sender'],
        sp,
        data['total'],
        data['decimals'],
        False,
        asset_name=data['name'],
        unit_name=data['unit_name'],
    )

    txgroup = []
    txgroup.append({'txn': encoding.msgpack_encode(acfg_txn)})
    return JsonResponse(txgroup, safe=False)

def new_pool(request):
    # If a wallet hasn't been selected and set in the cookie, redirect them.
    if 'account' not in request.COOKIES:
        return redirect('/')
    template = loader.get_template("staking/new_pool.html")
    context = {}
    return HttpResponse(template.render(context, request))

# API: This endpoint is requested via an in-page call.
def create_pool(request):
    data = json.loads(request.body)

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = constants.MIN_TXN_FEE

    # Hardcoded contracts, although it should probably be compiled on the fly
    # from the .teal files incase of modification.
    approval_prog_b64 = 'BiADAQAEJgwCU0ECQVMCQVICUkECVFICVFMCQlQCRVQBUAJMVQJGUgFBNhoAgASHj9TQEkAATzYaAIAEwJ3I7xJAAIQ2GgCABD53ak4SQAF7NhoAgASg6BhyEkABhTYaAIAEH6BpGRJAAJ42GgCABC5XG98SQADHNhoAgAS+DMOFEkABBgCIAWwxGSMSMRkiEhFEMRY1ADQAIgk1ATEANAE4ABJENAE4FDIKEkQxAIgCEiMpSmI0ATgSCGYnBUlkNAE4EghnIkOIASoxGSMSMRmBAhIRRDEAiAHpNhoBF8AwNhoCFzYaAxfAHIgBJjEZQQAUNhoDF8AcKWIURDYaAxfAHCpiFEQiQzEYFEQjwByIAN0oNhoBF8AwZys2GgIXwDBnJwY2GgMXSTIHDURnJwc2GgQXSTYaAxcNRGciQ4gAvjEWNQA0ACIJNQE0ATgHMgoSRDIKYDQBOAgIMgExMSIICzIAMTELCA9EIjUCNAIxMQ5BABM0AsAaF8AwiACINAIiCDUCQv/lIkOIAHIxFjUANAAiCTUBNAE4ECQSRDQBOBQyChJENAE4EStkEkSAAlBTK2RxAURnJwRJZDQBOBIIZycKNhoBF2ciQ4gAMScINhoBFxQUZzYaAhfAHIgADyJDiAAaiAASMRkkEkQiQycLTGeJJwhkFESJJwhkRIkxACcLZBJEibGyESSyEDIKshSziTUMNQs1CjQLNAwqKTQKKGQSTWJJNQ0OQAAENA01CzQMKik0CihkEk1KYjQLCWYnBCcFNAooZBJNSWQ0CwlnsSSyEDQKshE0C7ISNAyyFCOyAbOJNTIyCihkcABESTUzQQAfgAZTaGFyZXNkSTU0QQAQNDI0Mx0jNDQfSEhMIxJEiTQyiTVRNVA0UShKYjRQCGYnBUlkNFAIZ4k1UTVQNFErSmI0UAlmJwRJZDRQCWeJNTwyBycGZA1BAFM0PCcJYicHZAxBAEc0PCliNT0yBycHZEoNTTQ8JwliJwZkSgxNCTU+ND00Ph2B4I+GD5cnCmQLgZBOCjU/ND9BABEnBElkND8JZzQ8KkpiND8IZjQ8JwkyB0pnZok='
    clear_prog_b64 = 'BoEB'

    # We will use the Atomic Transaction Composer and as a result will need to
    # read the ABI JSON for the staking contract.
    with open("staking/contracts/staking.json") as f:
        js = f.read()
    c = Contract.from_json(js)

    # We create a blank signer, since we intend to use the ATC purely to help
    # construct the transaction group. The signer will be external to this
    # process, such as AlgoSigner that's an extension on the users browser.
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner('')

    # Add the 'deploy' method call. Used when deploying the staking smart
    # contract for the first time.
    atc.add_method_call(
        0,
        get_method(c, 'deploy'),
        data['sender'],
        sp,
        signer,
        method_args=[
            int(data['staking']),
            int(data['reward']),
            int(dateutil.parser.parse(data['begin']).timestamp()),
            int(dateutil.parser.parse(data['end']).timestamp()),
        ],
        local_schema=transaction.StateSchema(3, 0),
        global_schema=transaction.StateSchema(10, 1),
        approval_program=base64.b64decode(approval_prog_b64),
        clear_program=base64.b64decode(clear_prog_b64),
    )

    txgroup = []
    for tx in atc.build_group():
        txgroup.append({'txn': encoding.msgpack_encode(tx.txn)})
    return JsonResponse(txgroup, safe=False)
    
# The second step of deploying a pool is initialising it. The involves sending
# the minimum balance requirement (Algo). We also combine the final step of
# configuring the fixed rate of reward and funding the staking contract, since
# they can be grouped together.
def init_pool(request):
    data = json.loads(request.body)

    # Calculate the new smart contract address, and retrieve the application
    # state.
    pool_id = data['pool_id']
    pool_addr = logic.get_application_address(pool_id)
    app = algod_client.application_info(pool_id)

    # Decode the application's state to use the values.
    for s in app['params']['global-state']:
        match base64.b64decode(s['key']).decode('utf8'):
            case "SA":
                staking_asset = s['value']['uint']
            case "RA":
                reward_asset = s['value']['uint']
            case "BT":
                begin_timestamp = s['value']['uint']
            case "ET":
                end_timestamp = s['value']['uint']

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = constants.MIN_TXN_FEE

    # We will use the Atomic Transaction Composer and as a result will need to
    # read the ABI JSON for the staking contract.
    with open("staking/contracts/staking.json") as f:
        js = f.read()
    c = Contract.from_json(js)

    # We create a blank signer, since we intend to use the ATC purely to help
    # construct the transaction group. The signer will be external to this
    # process, such as AlgoSigner that's an extension on the users browser.
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner('')

    # Construct the Payment transaction, for 0.302 Algo, the minimum balance
    # for the smart contract account.
    # We create a TransactionWithSigner object although we have a blank signer,
    # as that's what the ATC expects.
    pay_txn = transaction.PaymentTxn(data['sender'], sp, pool_addr, 302000)
    pay_tws = TransactionWithSigner(pay_txn, signer)

    # Add the 'init' method call. This expects the payment transaction, along
    # with the two assets which it will optin to.
    atc.add_method_call(
        data['pool_id'],
        get_method(c, 'init'),
        data['sender'],
        sp,
        signer,
        method_args=[
            pay_tws,
            staking_asset,
            reward_asset,
        ],
    )

    # We're also going to include another method call 'reward', which sets the
    # fixed rate of return and also expects an asset transfer transacation.
    ra = algod_client.asset_info(reward_asset)

    # For this demo we will also send the full amount of reward assets to the
    # staking pool.
    all_rewards = ra['params']['total']

    # Convert the decimal percentage value to basis points.
    fixed_rate = int(data['fixed-rate'] * 100)

    # Construct the asset transfer transaction, to send the full amount of
    # reward asset into the staking pool.
    axfer_txn = transaction.AssetTransferTxn(data['sender'], sp, pool_addr, all_rewards, reward_asset)
    axfer_tws = TransactionWithSigner(axfer_txn, signer)

    # Add the 'reward' method call. This expects the asset transfer
    # transaction, along with the fixed rate of return, and the reward asset.
    atc.add_method_call(
        data['pool_id'],
        get_method(c, 'reward'),
        data['sender'],
        sp,
        signer,
        method_args=[
            axfer_tws,
            fixed_rate,
            reward_asset,
        ],
    )

    txgroup = []
    for tx in atc.build_group():
        txgroup.append({'txn': encoding.msgpack_encode(tx.txn)})
    return JsonResponse(txgroup, safe=False)

# API: This endpoint is requested via an in-page call.
def deposit(request, pool_id):
    data = json.loads(request.body)

    # Calculate the smart contract address, retrieve the application state,
    # and the users local state.
    pool_addr = logic.get_application_address(pool_id)
    app = algod_client.application_info(pool_id)
    acc = algod_client.account_info(data['sender'])

    # Assume we're going to make an OptIn call transaction unless we find the
    # user has already opted in.
    oncomp = transaction.OnComplete.OptInOC
    for als in acc['apps-local-state']:
        if als['id'] == pool_id:
            oncomp = transaction.OnComplete.NoOpOC
            break

    # Retrieve the reward asset ID for create the asset transfer transaction.
    for gs in app['params']['global-state']:
        if base64.b64decode(gs['key']).decode('utf8') == "SA":
            reward_asset = gs['value']['uint']

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = 1_000

    # We will use the Atomic Transaction Composer and as a result will need to
    # read the ABI JSON for the staking contract.
    with open("staking/contracts/staking.json") as f:
        js = f.read()
    c = Contract.from_json(js)

    # We create a blank signer, since we intend to use the ATC purely to help
    # construct the transaction group. The signer will be external to this
    # process, such as AlgoSigner that's an extension on the users browser.
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner('')

    # Construct the asset transfer transaction, to send the full amount of
    # reward asset into the staking pool.
    axfer_txn = transaction.AssetTransferTxn(data['sender'], sp, pool_addr, data['amount'], reward_asset)
    axfer_tws = TransactionWithSigner(axfer_txn, signer)

    # Add the 'deposit' method call. This expects the asset transfer
    # transaction, along with the reward asset.
    atc.add_method_call(
        pool_id,
        get_method(c, 'deposit'),
        data['sender'],
        sp,
        signer,
        method_args=[
            axfer_tws,
            reward_asset,
        ],
        on_complete=oncomp,
    )

    txgroup = []
    for tx in atc.build_group():
        txgroup.append({'txn': encoding.msgpack_encode(tx.txn)})
    return JsonResponse(txgroup, safe=False)

# API: This endpoint is requested via an in-page call.
def withdraw(request, pool_id):
    data = json.loads(request.body)

    # Calculate the smart contract address, retrieve the application state,
    # and the users local state.
    pool_addr = logic.get_application_address(pool_id)
    app = algod_client.application_info(pool_id)
    acc = algod_client.account_info(data['sender'])

    # Retrieve the staking and reward asset IDs,
    for gs in app['params']['global-state']:
        match base64.b64decode(gs['key']).decode('utf8'):
            case "SA":
                staking_asset = gs['value']['uint']
            case "RA":
                reward_asset = gs['value']['uint']

    # Retrieve the amount staked and claimed amount rewarded from the users
    # local state.
    for ls in acc['apps-local-state']:
        if ls['id'] == pool_id:
            for ls in ls['key-value']:
                match base64.b64decode(ls['key']).decode('utf8'):
                    case "AS":
                        amount_staked = ls['value']['uint']
                    case "AR":
                        amount_rewarded = ls['value']['uint']

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = constants.MIN_TXN_FEE * 2

    # We will use the Atomic Transaction Composer and as a result will need to
    # read the ABI JSON for the staking contract.
    with open("staking/contracts/staking.json") as f:
        js = f.read()
    c = Contract.from_json(js)

    # The value below is the maximum value that can be stored in a uint64.
    # 2^64 - 1
    # This value tells the smart contract to withdraw the maximum available for
    # the user. Including any newly calculated rewards since the transaction
    # was signed.
    all_available = 18446744073709551615

    # We create a blank signer, since we intend to use the ATC purely to help
    # construct the transaction group. The signer will be external to this
    # process, such as AlgoSigner that's an extension on the users browser.
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner('')

    # Are we withdrawing just the staking asset, or the staking asset and the
    # reward asset?
    if (data['all']):
        # We assume if you're withdrawing both you want the maximum available
        # of both assets.
        amount_staked = all_available
        amount_rewarded = all_available

        # Add 'withdraw' method call for the staking asset.
        atc.add_method_call(
            pool_id,
            get_method(c, 'withdraw'),
            data['sender'],
            sp,
            signer,
            method_args=[
                staking_asset,
                amount_staked,
                data['sender'],
            ],
        )

        # Add 'withdraw' method call for the reward asset.
        atc.add_method_call(
            pool_id,
            get_method(c, 'withdraw'),
            data['sender'],
            sp,
            signer,
            method_args=[
                reward_asset,
                amount_rewarded,
                data['sender'],
            ],
        )
    else:
        # Add 'withdraw' method call for the staking asset.
        atc.add_method_call(
            pool_id,
            get_method(c, 'withdraw'),
            data['sender'],
            sp,
            signer,
            method_args=[
                staking_asset,
                data['amount'],
                data['sender'],
            ],
        )

    txgroup = []
    for tx in atc.build_group():
        txgroup.append({'txn': encoding.msgpack_encode(tx.txn)})
    return JsonResponse(txgroup, safe=False)

# API: This endpoint is requested via an in-page call.
def claim(request, pool_id):
    data = json.loads(request.body)

    # Retrieve pool and account from the algod node.
    app = algod_client.application_info(pool_id)
    acc = algod_client.account_info(data['sender'])

    # Fetch additional details from the pool state (e.g. asset details).
    for gs in app['params']['global-state']:
        match base64.b64decode(gs['key']).decode('utf8'):
            case "SA":
                staking_asset = gs['value']['uint']
            case "RA":
                reward_asset = gs['value']['uint']

    # Fetch suggested parameters.
    sp = algod_client.suggested_params()
    sp.flat_fee = True
    sp.fee = constants.MIN_TXN_FEE * 2

    # We will use the Atomic Transaction Composer and as a result will need to
    # read the ABI JSON for the staking contract.
    with open("staking/contracts/staking.json") as f:
        js = f.read()
    c = Contract.from_json(js)

    # We create a blank signer, since we intend to use the ATC purely to help
    # construct the transaction group. The signer will be external to this
    # process, such as AlgoSigner that's an extension on the users browser.
    atc = AtomicTransactionComposer()
    signer = AccountTransactionSigner('')

    # The value below is the maximum value that can be stored in a uint64.
    # 2^64 - 1
    # This value tells the smart contract to withdraw the maximum available for
    # the user. Including any newly calculated rewards since the transaction
    # was signed.
    amount_rewarded = 18446744073709551615

    # Add 'withdraw' method call for the reward asset.
    atc.add_method_call(
        pool_id,
        get_method(c, 'withdraw'),
        data['sender'],
        sp,
        signer,
        method_args=[
            reward_asset,
            amount_rewarded,
            data['sender'],
        ],
    )

    txgroup = []
    for tx in atc.build_group():
        txgroup.append({'txn': encoding.msgpack_encode(tx.txn)})
    return JsonResponse(txgroup, safe=False)

# API: This endpoint is requested via an in-page call.
def submit(request):
    data = json.loads(request.body)

    # Encode all signed transactions sent to us and place them in an array.
    txgroup = []
    for stx in data:
        txgroup.append(encoding.future_msgpack_decode(stx['blob']))

    # Attempt to submit the transaction to the algod node. Catching any errors
    # and returning the status to the caller.
    try:
        algod_client.send_transactions(txgroup)
        result = {'success': True, 'message': "Transactions received."}
    except Exception as e:
        print(e)
        result = {'success': False, 'message': "Transaction failed."}

    return JsonResponse(result)

