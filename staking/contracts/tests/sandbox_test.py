#!/usr/bin/env python

"""
Test script using sandbox.

Only for demonstration purposes.
"""

import logging
import os
from re import A
import sys
import time
from datetime import datetime

import algosdk.future.transaction as txn
from algosdk import abi, logic
from algosdk.atomic_transaction_composer import (
    AccountTransactionSigner,
    AtomicTransactionComposer,
    TransactionWithSigner,
)

from goal import Goal

stamp = datetime.now().strftime("%Y,%m/%d_%H:%M:%S")
print(f"{os.path.basename(sys.argv[0])} start {stamp}")

# Initialize to sandbox.
goal = Goal(
    name="unencrypted-default-wallet",
    algod_token=("a" * 64),
    algod_address="http://localhost:4001",
    kmd_token=("a" * 64),
    kmd_address="http://localhost:4002",
)

# App parameters
creator = goal.account
creator_sk = goal.sk
current_time = int(time.time())
begin_time = current_time + 25
end_time = begin_time + 325
fixed_rate = 1000  # 10%
print(f"UNIX time {current_time}")

staking_asset_id = 0
reward_asset_id = 0
app_id = 0

# ATC and helpers
atc = AtomicTransactionComposer()
creator_signer = AccountTransactionSigner(creator_sk)

# Create staking asset
staking_asset_total = 1_000_000_000_000_000
acfg = goal.acfg(
    creator,
    total=staking_asset_total,
    unit_name="SA",
    asset_name="Staking Asset",
)
txinfo, err = goal.send(acfg)
assert not err, err
staking_asset_id = txinfo["asset-index"]
assert goal.balance(creator, staking_asset_id) == staking_asset_total
logging.debug(f"Created staking asset: {staking_asset_id}")


# # Create reward asset
reward_asset_total = 1_000_000_000_000
acfg = goal.acfg(
    creator,
    total=reward_asset_total,
    unit_name="RA",
    asset_name="Reward Asset",
)
txinfo, err = goal.send(acfg)
assert not err, err
reward_asset_id = txinfo["asset-index"]
assert goal.balance(creator, reward_asset_id) == reward_asset_total
logging.debug(f"Created reward asset: {reward_asset_id}")

# Compile contract
teal = "pyteal_staking.teal"
clear_teal = "pyteal_clear.teal"
approval = goal.assemble(teal)
clear_prog = goal.assemble(clear_teal)

# Deploy new staking contract
deploy_method_args = [staking_asset_id, reward_asset_id, begin_time, end_time]
abi_deploy_method = abi.Method.from_signature("deploy(asset,asset,uint64,uint64)void")
atc.add_method_call(
    app_id=0,
    method=abi_deploy_method,
    sender=creator,
    sp=goal.algod.suggested_params(),
    signer=creator_signer,
    method_args=deploy_method_args,
    on_complete=txn.OnComplete.NoOpOC,
    local_schema=txn.StateSchema(3, 0),
    global_schema=txn.StateSchema(10, 1),
    approval_program=approval,
    clear_program=clear_prog,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
deploy_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(deploy_results.tx_ids[0])
app_id = txinfo["application-index"]
assert app_id
print(f"App ID {app_id}")

# Check some contract invariants for deployment
global_state = goal.app_read(app_id)
logging.debug(global_state)
assert global_state[b"BT"] < global_state[b"ET"]
assert global_state[b"SA"] == staking_asset_id
assert global_state[b"RA"] == reward_asset_id
print("Deploy complete")


# Create minimum balance payment to staking contract
appl_addr = logic.get_application_address(app_id)
pay_minbal = goal.pay(goal.account, receiver=appl_addr, amt=302000)

# Initialize staking contract
atc = AtomicTransactionComposer()
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("init(pay,asset,asset)void"),
    sender=creator,
    sp=goal.algod.suggested_params(),
    signer=creator_signer,
    method_args=[
        TransactionWithSigner(pay_minbal, creator_signer),
        staking_asset_id,
        reward_asset_id,
    ],
    on_complete=txn.OnComplete.NoOpOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
init_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(init_results.tx_ids[0])
logging.debug(f"Init tx: {txinfo}\n")

global_state = goal.app_read(app_id)
logging.debug(f"Global {global_state}\n")
print("Init complete")


# Transfer rewards to staking contract
atc = AtomicTransactionComposer()
reward_axfer = goal.axfer(creator, appl_addr, reward_asset_total, reward_asset_id)
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("reward(axfer,uint64,asset)void"),
    sender=creator,
    sp=goal.algod.suggested_params(),
    signer=creator_signer,
    method_args=[
        TransactionWithSigner(reward_axfer, creator_signer),
        fixed_rate,
        reward_asset_id,
    ],
    on_complete=txn.OnComplete.NoOpOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
reward_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(reward_results.tx_ids[0])
logging.debug(f"reward tx: {txinfo}\n")

global_state = goal.app_read(app_id)
logging.debug(f"Global {global_state}\n")
assert global_state[b"FR"] == fixed_rate
assert global_state[b"TR"] == reward_asset_total
print("Reward complete")


# Deposit staked assets
atc = AtomicTransactionComposer()
deposit_axfer = goal.axfer(creator, appl_addr, staking_asset_total, staking_asset_id)
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("deposit(axfer,asset)void"),
    sender=creator,
    sp=goal.algod.suggested_params(),
    signer=creator_signer,
    method_args=[
        TransactionWithSigner(deposit_axfer, creator_signer),
        reward_asset_id,
    ],
    on_complete=txn.OnComplete.OptInOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
reward_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(reward_results.tx_ids[0])
logging.debug(f"Deposit tx: {txinfo}\n")

global_state = goal.app_read(app_id)
logging.debug(f"Global {global_state}\n")
assert global_state[b"TS"] == staking_asset_total

local_state = goal.app_read(app_id, creator)
logging.debug(f"Local {local_state}\n")
last_update_account = local_state[b"LU"]
assert local_state[b"AR"] == 0
assert local_state[b"AS"] == staking_asset_total
assert last_update_account > current_time  # Assert that this was updated
print("Deposit complete")


time.sleep(10)

# Withdraw reward assets
# Need extra fees to cover withdrawal
sp_withdraw = goal.algod.suggested_params()
sp_withdraw.fee = 2000
reward_withdraw_amt = 10
atc = AtomicTransactionComposer()
atc.add_method_call(
    app_id=app_id,
    method=abi.Method.from_signature("withdraw(asset,uint64,account)void"),
    sender=creator,
    sp=sp_withdraw,
    signer=creator_signer,
    method_args=[reward_asset_id, reward_withdraw_amt, creator],
    on_complete=txn.OnComplete.NoOpOC,
    foreign_assets=[staking_asset_id, reward_asset_id],
)
reward_results = atc.execute(goal.algod, 10)
txinfo = goal.confirm(reward_results.tx_ids[0])
logging.debug(f"Withdraw tx: {txinfo}\n")

global_state = goal.app_read(app_id)
logging.debug(f"Global {global_state}\n")

local_state = goal.app_read(app_id, creator)
logging.debug(f"Local {local_state}\n")
assert local_state[b"AR"]
assert local_state[b"AS"] == staking_asset_total
assert local_state[b"LU"] > last_update_account
assert (
    local_state[b"AR"] + global_state[b"TR"] + reward_withdraw_amt
) == reward_asset_total
